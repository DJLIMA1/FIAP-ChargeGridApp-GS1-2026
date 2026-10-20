from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from chargegrid_core import pricing
from chargegrid_core.forecast import aggregate, baseline, engine, evaluate, insights, offline, synthetic
from chargegrid_core.forecast.best_times import best_times, expected_multiplier
from chargegrid_core.forecast.calendar import day_word, is_holiday, to_local, to_utc, window_text
from chargegrid_core.forecast.features import FEATURES
from chargegrid_core.forecast.gbm import raw_predict
from chargegrid_core.forecast.series import StationSeries, build_series

UTC = timezone.utc


def at(hour, minute=0, day=20):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def session(sid="s1", start=None, end=None, energy="0", connector="c1", source="simulated"):
    return {"id": sid, "connector_id": connector, "started_at": start, "ended_at": end, "energy_wh": energy,
            "source": source, "status": "completed"}


# ------------------------------------------------------------------ agregados

def test_busy_seconds_split_across_hours():
    rows = aggregate.hourly_rows([session(start=at(17, 40), end=at(19, 10))], [], at(17), at(20), at(21))
    assert [(r["hour_start"].hour, r["busy_seconds"]) for r in rows] == [(17, 1200), (18, 3600), (19, 600)]
    assert rows[0]["sessions_started"] == 1 and rows[1]["sessions_started"] == 0


def test_energy_from_telemetry_deltas_conserves_total_and_ignores_regression():
    samples = [{"session_id": "s1", "captured_at": at(17, 50), "energy_wh": "500", "power_w": "3000"},
               {"session_id": "s1", "captured_at": at(18, 30), "energy_wh": "2500", "power_w": "3100"},
               # reboot: o contador volta a zero e não pode gerar energia negativa
               {"session_id": "s1", "captured_at": at(18, 40), "energy_wh": "100", "power_w": "0"},
               {"session_id": "s1", "captured_at": at(19, 0), "energy_wh": "900", "power_w": "2900"}]
    rows = aggregate.hourly_rows([session(start=at(17, 40), end=at(19, 10), energy="3800")], samples,
                                 at(17), at(20), at(21))
    energies = {r["hour_start"].hour: r["energy_wh"] for r in rows}
    assert sum(energies.values()) == Decimal("3800.000")  # nunca soma cumulativos
    assert all(value >= 0 for value in energies.values())
    assert energies[17] == Decimal("500.000") + Decimal("500.000")  # 17:50→18:30 dividido no tempo
    assert {r["energy_basis"] for r in rows} == {"telemetry"}
    assert rows[0]["max_power_w"] == Decimal("3000")


def test_energy_spread_when_telemetry_is_gone():
    rows = aggregate.hourly_rows([session(start=at(17, 30), end=at(18, 30), energy="1000")], [],
                                 at(17), at(19), at(20))
    assert [r["energy_wh"] for r in rows] == [Decimal("500.000"), Decimal("500.000")]
    assert {r["energy_basis"] for r in rows} == {"session_spread"}
    assert {r["origin"] for r in rows} == {"simulated"}


def test_active_session_counts_only_until_now_and_inside_window():
    rows = aggregate.hourly_rows([session(start=at(17, 30), end=None)], [], at(17), at(19), at(18, 15))
    assert [(r["hour_start"].hour, r["busy_seconds"]) for r in rows] == [(17, 1800), (18, 900)]
    assert aggregate.hourly_rows([session(start=at(10), end=at(11))], [], at(17), at(19), at(20)) == []


def test_measured_origin_only_when_every_session_is_measured():
    rows = aggregate.hourly_rows([session(start=at(17), end=at(17, 30), source="measured")], [],
                                 at(17), at(18), at(19))
    assert rows[0]["origin"] == "measured"


def test_series_is_local_time_and_real_data_beats_synthetic():
    rows = [{"connector_id": "c1", "hour_start": at(20), "origin": "synthetic", "busy_seconds": 3600, "energy_wh": 7000},
            {"connector_id": "c1", "hour_start": at(20), "origin": "simulated", "busy_seconds": 1800, "energy_wh": 3000},
            {"connector_id": "c2", "hour_start": at(21), "origin": "simulated", "busy_seconds": 3600, "energy_wh": 0}]
    start = datetime(2026, 10, 20, 16)  # 16h local = 19h UTC
    series = build_series(rows, 2, start, start + timedelta(hours=4))
    assert series.occ == [None, 0.25, 0.5, 0.0]  # 20h UTC = 17h local; sem linha depois do início = 0
    assert series.kwh[1] == 3.0
    assert to_local(at(20)) == datetime(2026, 10, 20, 17) and to_utc(datetime(2026, 10, 20, 17)) == at(20)


# ---------------------------------------------------------------- calendário

def test_holidays_and_labels():
    assert is_holiday(datetime(2026, 11, 20).date()) and is_holiday(datetime(2026, 2, 17).date())  # Carnaval
    assert not is_holiday(datetime(2026, 10, 21).date())
    today = datetime(2026, 10, 20).date()
    assert day_word(today, today) == "Hoje" and day_word(datetime(2026, 10, 21).date(), today) == "Amanhã"
    assert day_word(datetime(2026, 10, 22).date(), today) == "Quinta-feira"
    assert window_text(datetime(2026, 10, 21, 17), datetime(2026, 10, 21, 19)) == "17h–19h"
    assert window_text(datetime(2026, 10, 21, 22), datetime(2026, 10, 22, 0)) == "22h–24h"


# ------------------------------------------------------------------ baseline

def flat_series(weeks=5, value_at=lambda i: 0.0, connectors=2, start=datetime(2026, 9, 7)):
    occ = [value_at(i) for i in range(weeks * 168)]
    return StationSeries(start=start, occ=occ, kwh=[v * connectors * 7 for v in occ], connectors=connectors,
                         synthetic=[False] * len(occ))


def test_baseline_weighted_same_weekday_hour_shrunk_to_hour_mean():
    occ = [0.0] * (5 * 168)
    origin = 4 * 168
    t = origin + 18  # segunda 18h
    for k, value in enumerate((0.8, 0.6, 0.4, 0.2), start=1):
        occ[t - 168 * k] = value
    mean_dh = (0.4 * 0.8 + 0.3 * 0.6 + 0.2 * 0.4 + 0.1 * 0.2)
    mean_h = 0.8 / 7  # só a segunda passada tinha movimento às 18h nos últimos 7 dias
    assert baseline.baseline(occ, t, origin) == pytest.approx((4 * mean_dh + 2 * mean_h) / 6)


def test_baseline_never_reads_the_future_and_handles_little_history():
    occ = [None] * 168 + [0.5] * 24 + [None] * 200
    origin = 168 + 24
    assert baseline.baseline(occ, origin + 5, origin) == pytest.approx(0.5)  # só a média da hora
    assert baseline.baseline([None] * 400, 300, 200) is None
    changed = occ[:origin] + [1.0] * (len(occ) - origin)
    assert baseline.baseline(changed, origin + 5, origin) == baseline.baseline(occ, origin + 5, origin)


# ------------------------------------------------------------------ métricas

def test_metrics_and_zero_denominator():
    result = evaluate.metrics([0.5, 0.0, 0.5], [0.25, 0.25, 0.5])
    assert result["mae_pp"] == pytest.approx(16.67) and result["wape"] == 0.5 and result["accuracy_percent"] == 50.0
    assert evaluate.metrics([0.0, 0.0], [0.1, 0.0])["wape"] is None
    assert evaluate.model_wins({"wape": 0.20}, {"wape": 0.25}) and not evaluate.model_wins({"wape": 0.24}, {"wape": 0.25})


def test_backtest_uses_only_past_data():
    series = flat_series(weeks=6, value_at=lambda i: 0.6 if 17 <= i % 24 <= 19 else 0.05)
    as_of = 6 * 168 - 30
    first = evaluate.backtest(series, as_of, None)
    changed = StationSeries(start=series.start, occ=series.occ[:as_of] + [1.0] * (len(series.occ) - as_of),
                            kwh=series.kwh, connectors=2, synthetic=series.synthetic)
    assert evaluate.backtest(changed, as_of, None)["baseline"] == first["baseline"]
    assert first["origins"] == 14 and first["baseline"]["mae_pp"] == 0.0


def test_choose_falls_back_to_baseline():
    good = {"origins": 14, "baseline": {"wape": 0.3, "mae_pp": 10}, "gbm": {"wape": 0.2, "mae_pp": 7}}
    worse = {**good, "gbm": {"wape": 0.29, "mae_pp": 9.9}}
    assert evaluate.choose(good, {"x": 1}, "gbm")[0] == "gbm"
    assert evaluate.choose(worse, {"x": 1}, "gbm")[0] == "baseline"
    assert evaluate.choose(good, {"x": 1}, "baseline")[0] == "baseline"
    assert evaluate.choose({**good, "origins": 3}, {"x": 1}, "gbm")[0] == "baseline"


# ----------------------------------------------------------------- sintético

def test_synthetic_is_deterministic_labeled_and_respects_capacity():
    profile = synthetic.station_profile(7, 2)
    first = synthetic.station_rows(profile, datetime(2025, 3, 3), 14)
    assert first == synthetic.station_rows(profile, datetime(2025, 3, 3), 14)
    assert {row["origin"] for row in first} == {"synthetic"} and {row["energy_basis"] for row in first} == {"synthetic"}
    assert all(0 <= row["busy_seconds"] <= 3600 for row in first)
    series, ratios = synthetic.station_series(profile, datetime(2025, 3, 3), 14)
    assert all(value is not None and 0 <= value <= 1 for value in series.occ)
    assert series.coverage()["days_synthetic"] == 14 and len(ratios) == len(series.occ)


# --------------------------------------------------------------- previsão

def busy_evenings(weeks=6, connectors=2):
    return flat_series(weeks, lambda i: 0.95 if 17 <= i % 24 < 19 else (0.02 if 13 <= i % 24 < 17 else 0.3),
                       connectors)


CONNECTORS = [{"id": "c1", "public_code": "CG-1", "price_per_kwh": Decimal("2.0000"), "power_kw": 7.4},
              {"id": "c2", "public_code": "CG-2", "price_per_kwh": Decimal("2.0000"), "power_kw": 7.4}]


def test_forecast_finds_peak_and_suggests_pricing_with_baseline_model():
    series = busy_evenings()
    now_local = series.at(len(series.occ)) + timedelta(minutes=10)
    result = engine.station_forecast(series, now_local, rules={"demand": {"max_increase_percent": 20}},
                                     connectors=CONNECTORS, use_default_model=False)
    assert result["status"] == "ok" and result["method"] == "baseline" and len(result["hours"]) == 36
    assert result["accuracy"]["status"] == "ok" and result["accuracy"]["baseline"]["mae_pp"] == 0.0
    assert any(peak["label"].endswith("17h–19h deve lotar") for peak in result["peaks"])
    kinds = [item["kind"] for item in result["suggestions"]]
    assert kinds[0] == "raise_demand_cap" and "schedule_peak" in kinds
    peak = next(item for item in result["suggestions"] if item["kind"] == "schedule_peak")
    patch = peak["action"]["patch"]
    rules = pricing.clean_rules(pricing.merge_rules(pricing.stored_rules({}), patch, ["c1", "c2"]))
    interval = rules["schedule"]["intervals"][0]
    assert (interval["start"], interval["end"], interval["prices"]["c1"]) == ("17:00", "19:00", "2.2000")
    assert peak["action"]["preview"][0] == {"connector_id": "c1", "public_code": "CG-1", "from": "2.0000",
                                            "to": "2.2000"}
    full = [hour for hour in result["hours"] if hour["full"]]
    assert full and Decimal(full[0]["expected_multiplier"]) > 1
    assert result["includes_synthetic"] is False and result["model"] is None


def test_forecast_without_history_and_synthetic_label():
    empty = StationSeries(start=datetime(2026, 9, 1), occ=[None] * 48, kwh=[None] * 48, connectors=1)
    result = engine.station_forecast(empty, datetime(2026, 9, 3, 0, 5), rules={}, connectors=CONNECTORS[:1],
                                     use_default_model=False)
    assert result["status"] == "no_history" and result["hours"] == [] and result["suggestions"] == []
    profile = synthetic.station_profile(3, 0)
    series, _ = synthetic.station_series(profile, datetime(2026, 8, 3), 42)
    labeled = engine.station_forecast(series, series.at(len(series.occ)), rules={}, connectors=CONNECTORS,
                                      use_default_model=False)
    assert labeled["includes_synthetic"] and engine.SYNTHETIC_NOTE in labeled["notes"]


def test_schedule_suggestion_skips_overlapping_interval():
    series = busy_evenings()
    rules = {"schedule": {"enabled": True, "intervals": [
        {"start": "16:00", "end": "20:00", "days": [0, 1, 2, 3, 4, 5, 6], "prices": {"c1": "2.5"}}]}}
    result = engine.station_forecast(series, series.at(len(series.occ)), rules=rules, connectors=CONNECTORS,
                                     use_default_model=False)
    assert "schedule_peak" not in [item["kind"] for item in result["suggestions"]]


def test_idle_window_suggests_cheaper_schedule():
    peaks, idle = insights.peaks_and_idle(
        [(datetime(2026, 10, 21, h), 0.02 if 13 <= h < 17 else 0.5) for h in range(24)], datetime(2026, 10, 20).date())
    assert not peaks and idle[0]["label"] == "Amanhã 13h–17h deve ficar vazio"
    advice = insights.suggestions({}, CONNECTORS, peaks, idle)
    assert advice[0]["kind"] == "schedule_idle"
    assert advice[0]["action"]["patch"]["schedule"]["intervals"][0]["prices"]["c2"] == "1.8000"


def test_occupancy_history_heatmap():
    history = engine.occupancy_history(busy_evenings(), weeks=4)
    assert history["occupancy_percent"][0][17] == "95.0" and history["samples"][0][17] == 4
    assert history["max_occupancy_percent"] == "95.0" and history["includes_synthetic"] is False


# ------------------------------------------------------------ melhor horário

def test_expected_multiplier_matches_pricing_rule():
    when = datetime(2026, 10, 21, 18)
    assert expected_multiplier({}, 4, 0.1, when) == Decimal("1.00")
    direct = pricing.demand_status({}, {"connectors": 4, "in_use": 4, "reserved": 0, "busy_15m": Decimal("1"),
                                        "starts_60m": 0, "baseline_60m": 0, "local_now": when})
    assert expected_multiplier({}, 4, 1.0, when) == Decimal(direct["multiplier"]) > 1


def test_best_times_prefers_cheaper_scheduled_hour_then_lower_occupancy():
    rules = {"schedule": {"enabled": True, "intervals": [
        {"start": "14:00", "end": "16:00", "days": [2], "prices": {"c1": "1.5000", "c2": "1.6000"}}]}}
    hours = [(datetime(2026, 10, 21, h), 0.3) for h in range(10, 22)]  # quarta-feira
    result = best_times(rules, CONNECTORS, hours, Decimal("2.0000"))
    assert result["best"]["start"].startswith("2026-10-21T14:00") and result["best"]["end"].startswith("2026-10-21T16:00")
    assert result["best"]["price_from"] == "1.5000" and result["best"]["saving_vs_now_percent"] == 25
    assert "14:00–16:00" in result["best"]["reason"]
    flat = best_times({}, CONNECTORS, [(datetime(2026, 10, 21, h), 0.5 if h != 15 else 0.1) for h in range(10, 14)]
                      + [(datetime(2026, 10, 21, 15), 0.1)], None)
    assert flat["stable"] and flat["best"]["start"].startswith("2026-10-21T15:00")
    assert "Estimativa" in flat["note"]


def test_station_best_times_uses_demand_forecast():
    series = busy_evenings()
    now_local = series.at(len(series.occ))
    result = engine.station_best_times(series, now_local, rules={}, connectors=CONNECTORS, now_price=Decimal("2.5"),
                                       hours=12)
    assert len(result["hours"]) == 12 and result["method"] in ("baseline", "gbm")
    assert Decimal(result["best"]["price_from"]) <= Decimal("2.5")


# -------------------------------------------------------------------- modelo

def test_model_artifact_reproduces_golden_predictions_and_selection_rule():
    model = engine.default_model()
    assert model is not None and model["features"] == list(FEATURES)
    for features, value in model["golden"]:
        assert raw_predict(model, features) == pytest.approx(value, abs=1e-9)
    test = model["offline_test"]
    assert model["selected"] == ("gbm" if evaluate.model_wins(test["gbm"], test["baseline"]) else "baseline")


def test_model_metrics_are_reproducible_from_the_synthetic_protocol():
    """Recalcula, sem scikit-learn, as métricas de verificação gravadas no artefato."""
    model = engine.default_model()
    assert offline.verification(model) == model["verification"]
