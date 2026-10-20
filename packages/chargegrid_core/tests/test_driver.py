import random
import time
from datetime import datetime

import pytest

from chargegrid_core.driver import (
    PRESETS,
    Amenity,
    BonusWindow,
    ChargeCurve,
    ChargerOption,
    CombinedDemand,
    DemandSignal,
    DriverPreferences,
    HeuristicDemand,
    Meal,
    WeatherSignal,
    base_multiplier,
    build_next_stop,
    build_plan,
    merge_profile,
    next_stop,
    options_from_stations,
    plan_shift,
    shift_window,
    validate_profile,
    vehicle_from_dict,
)

DOLPHIN = PRESETS['byd_dolphin']
TUESDAY = datetime(2026, 10, 13)  # terça-feira
CENTER = (-23.5505, -46.6333)


def at(hour, minute=0, day=TUESDAY):
    return day.replace(hour=hour, minute=minute)


def option(sid, *, dc=True, price=2.0, power=None, lat=-23.555, lng=-46.635, amenities=(), **extra):
    return ChargerOption(sid, f'Posto {sid}', lat, lng, 'ccs2' if dc else 'type2',
                         power or (60 if dc else 22), price, connector_id=f'{sid}-p', amenities=amenities, **extra)


def prefs(**changes):
    base = {'shift_start': 14 * 60, 'shift_end': 22 * 60, 'meals': (), 'reserve_percent': 15.0}
    base.update(changes)
    return DriverPreferences(**base)


def in_peak(stop):
    return stop['demand'] >= 1.3


# --- curva de demanda ---------------------------------------------------------------

def test_demand_curve_peaks_and_quiet_hours():
    assert base_multiplier(at(18)) >= 1.4
    assert base_multiplier(at(7, 30)) >= 1.4
    assert base_multiplier(at(3)) < 0.6
    assert base_multiplier(at(15)) < 1.0
    friday_night = base_multiplier(datetime(2026, 10, 16, 23))
    assert friday_night > base_multiplier(at(23))
    assert base_multiplier(datetime(2026, 10, 17, 1)) > 1.2  # madrugada de sábado
    assert base_multiplier(at(8), holiday=True) < base_multiplier(at(8))


def test_live_signals_multiply_heuristic_and_expose_source():
    weather = WeatherSignal({at(18): (4.0, 22.0), at(19): (0.5, 31.0)})
    combined = CombinedDemand(HeuristicDemand(), (weather,))
    assert isinstance(combined, DemandSignal)
    assert combined.source == 'heuristica+open-meteo'
    assert combined.multiplier(at(18, 15)) == pytest.approx(base_multiplier(at(18, 15)) * 1.35, rel=1e-3)
    assert weather.multiplier(at(19, 30)) == pytest.approx(1.2)
    assert weather.multiplier(at(21)) == 1.0
    assert weather.rainy_hours(at(17), at(20)) == [at(18), at(19)]
    bonus = HeuristicDemand(bonuses=(BonusWindow('Aeroporto', at(5), at(8), 1.2),))
    assert bonus.multiplier(at(6)) == pytest.approx(base_multiplier(at(6)) * 1.2)


# --- veículo e curva de carga -------------------------------------------------------------

def test_presets_are_estimates_and_charge_curve_tapers_after_80_percent():
    assert len(PRESETS) >= 8 and all(p.estimate for p in PRESETS.values())
    assert {'byd_dolphin', 'byd_dolphin_mini', 'byd_seal', 'byd_yuan_plus', 'gwm_ora_03',
            'renault_kwid_etech', 'volvo_ex30', 'chevrolet_bolt'} <= set(PRESETS)
    curve = ChargeCurve.for_connector('CCS2')
    low = curve.charge(50, 50, 0.2, 30) - 0.2
    high = curve.charge(50, 50, 0.8, 30) - 0.8
    assert low == pytest.approx(0.5)  # 25 kWh em 30 min a 50 kW
    assert 0 < high < low / 2
    end = curve.charge(50, 50, 0.3, 50)
    assert curve.minutes_to(50, 50, 0.3, end) == pytest.approx(50, rel=1e-6)
    assert curve.charge(50, 50, 0.5, 600, soc_cap=0.8) == pytest.approx(0.8)
    assert DOLPHIN.effective_power(150, 'ccs2') == 60 and DOLPHIN.effective_power(22, 'Tipo 2') == 6.6


def test_vehicle_and_preferences_validation():
    custom = vehicle_from_dict({'usable_battery_kwh': 50, 'name': 'Meu EV', 'connectors': ['Tipo 2']})
    assert custom.key == 'custom' and not custom.accepts('ccs2') and custom.accepts('type2')
    tuned = vehicle_from_dict({'preset': 'byd_seal', 'consumption_kwh_per_100km': 18})
    assert tuned.key == 'byd_seal' and tuned.consumption_kwh_per_100km == 18
    with pytest.raises(ValueError):
        vehicle_from_dict({'usable_battery_kwh': 1000})
    with pytest.raises(ValueError):
        DriverPreferences.from_dict({'reserve_percent': 45, 'max_charge_percent': 50})
    with pytest.raises(ValueError):
        DriverPreferences.from_dict({'shift_start': '06:00', 'shift_end': '23:30'})
    with pytest.raises(ValueError):
        DriverPreferences.from_dict({'shift_start': '25:00'})
    parsed = DriverPreferences.from_dict({'shift_start': '18h', 'shift_end': '02:00',
                                          'meals': [{'kind': 'lanche', 'start': '23:30', 'flexible': True}]})
    assert parsed.shift_minutes == 8 * 60 and parsed.meals[0].window == (23 * 60 + 30 - 120, 23 * 60 + 30 + 120)
    profile = validate_profile(merge_profile({'vehicle': {'preset': 'byd_seal'}},
                                             {'preferences': {'earnings_per_hour': 45}}))
    assert profile['vehicle']['preset'] == 'byd_seal' and profile['preferences']['earnings_per_hour'] == 45


def test_options_from_api_stations_filter_and_queue():
    stations = [
        {'id': 'a', 'name': 'A', 'latitude': -23.5, 'longitude': -46.6, 'active': True,
         'amenities': [{'kind': 'restaurante', 'name': 'Cantina', 'distance_m': 60}, {'kind': 'invalido'}],
         'connectors': [
             {'id': 'slow', 'connector_type': 'Tipo 2', 'power_kw': '22', 'price_per_kwh': '1.2',
              'available': True, 'online': True, 'availability_status': 'available'},
             {'id': 'fast', 'connector_type': 'CCS2', 'power_kw': '120', 'price_per_kwh': '2.5',
              'available': True, 'online': True, 'availability_status': 'available'}]},
        {'id': 'b', 'name': 'B', 'latitude': -23.5, 'longitude': -46.6,
         'connectors': [{'id': 'busy', 'connector_type': 'ccs', 'power_kw': '50', 'price_per_kwh': '2',
                         'available': False, 'online': True, 'availability_status': 'charging'}]},
        {'id': 'c', 'name': 'C', 'latitude': -23.5, 'longitude': -46.6,
         'connectors': [{'id': 'off', 'connector_type': 'ccs2', 'power_kw': '50', 'price_per_kwh': '2',
                         'available': False, 'online': False, 'availability_status': 'offline'}]},
        {'id': 'd', 'name': 'D', 'latitude': -23.5, 'longitude': -46.6, 'active': False, 'connectors': []},
        {'id': 'e', 'name': 'E', 'latitude': -23.5, 'longitude': -46.6,
         'connectors': [{'id': 'bench', 'connector_type': 'bench', 'power_kw': '1', 'price_per_kwh': '2',
                         'available': True, 'online': True, 'availability_status': 'available'}]},
    ]
    options = {o.station_id: o for o in options_from_stations(stations, DOLPHIN)}
    assert set(options) == {'a', 'b'}
    assert options['a'].connector_id == 'fast' and options['a'].power_kw == 60  # limitado pelo carro
    assert options['a'].meal_amenity('jantar').name == 'Cantina' and len(options['a'].amenities) == 1
    assert options['b'].available is False and options['b'].queue_minutes == 30
    ac_only = vehicle_from_dict({'preset': 'byd_dolphin', 'connectors': ['type2']})
    assert options_from_stations(stations, ac_only)[0].connector_id == 'slow'


# --- planejamento ----------------------------------------------------------------------

def test_peak_is_avoided_while_naive_strategy_stops_in_the_peak():
    stations = [option('near', lat=-23.552, lng=-46.634), option('far', lat=-23.60, lng=-46.70, price=1.9)]
    plan = plan_shift(DOLPHIN, prefs(), stations, at(14), at(22), 50, origin=CENTER).to_dict()
    assert plan['stops'], 'o turno exige recarga'
    assert not any(in_peak(stop) for stop in plan['stops'])
    assert plan['totals']['peak_stop_minutes'] == 0
    naive = plan['baseline']
    assert naive['totals']['peak_stop_minutes'] > 0
    assert plan['comparison']['peak_stop_minutes_avoided'] > 0
    assert plan['comparison']['net_profit_gain'] > 0
    assert plan['totals']['net_profit'] > naive['totals']['net_profit']
    assert any(p['start'] <= '18:00' < p['end'] for p in plan['peaks'])
    assert 'pico de demanda' in plan['stops'][0]['reason']
    assert any(alert['code'] == 'peak' for alert in plan['alerts'])
    assert plan['estimate'] is True and plan['demand']['label'] == 'estimativa'


def test_dinner_is_coupled_with_charging_at_station_with_restaurant():
    restaurant = (Amenity('restaurante', 'Cantina', 50),)
    stations = [option('plain', price=1.8), option('food', price=2.2, lat=-23.56, lng=-46.64, amenities=restaurant)]
    dinner = Meal('jantar', 20 * 60, 45, 30)
    # 65%: a bateria dura até o jantar, mas não até o fim do turno.
    plan = plan_shift(DOLPHIN, prefs(meals=(dinner,)), stations, at(14), at(22), 65, origin=CENTER).to_dict()
    coupled = [stop for stop in plan['stops'] if stop['meal']]
    assert len(coupled) == 1
    stop = coupled[0]
    assert stop['station_id'] == 'food' and stop['meal'] == 'Jantar'
    assert stop['amenity'] == {'kind': 'restaurante', 'name': 'Cantina', 'distance_m': 50}
    assert '19:30' <= stop['start'] <= '20:30'
    assert stop['reason'].startswith('Jantar às') and 'restaurante a 50 m' in stop['reason']
    assert any(block['kind'] == 'refeicao_recarga' for block in plan['blocks'])
    assert not any(block['kind'] == 'refeicao' for block in plan['blocks'])  # refeição não duplicada
    assert len(plan['stops']) == 1 and plan['totals']['min_soc_percent'] >= 15
    # Carrega só o necessário: energia pública cara não sobra no fim do turno.
    assert plan['totals']['end_soc_percent'] < 25


def test_meal_without_amenity_is_taken_alone_and_reserve_respected():
    lunch = Meal('almoco', 12 * 60 + 30, 60, 30)
    stations = [option(f's{i}', lat=-23.55 + i / 100, price=2 + i / 10) for i in range(4)]
    preferences = prefs(shift_start=8 * 60, shift_end=20 * 60, meals=(lunch,))
    plan = plan_shift(DOLPHIN, preferences, stations, at(8), at(20), 35, origin=CENTER).to_dict()
    meals = [block for block in plan['blocks'] if block['kind'] == 'refeicao']
    assert len(meals) == 1 and '12:00' <= meals[0]['start'] <= '13:00'
    assert plan['totals']['min_soc_percent'] >= 15 - 0.5
    assert all(row['soc'] is None or row['soc'] >= 14.5 for row in plan['slots'])
    assert any(alert['code'] == 'needs_charge' for alert in plan['alerts'])
    assert not any(alert['code'] == 'reserve_violated' for alert in plan['alerts'])


def test_no_viable_station_produces_explicit_alerts():
    plan = plan_shift(DOLPHIN, prefs(), [], at(14), at(22), 25).to_dict()
    codes = {alert['code'] for alert in plan['alerts']}
    assert {'needs_charge', 'no_station', 'reserve_violated'} <= codes
    assert plan['stops'] == [] and plan['stations_considered'] == 0


def test_short_shift_with_enough_battery_needs_no_charge():
    plan = plan_shift(DOLPHIN, prefs(shift_start=9 * 60, shift_end=11 * 60), [option('a')],
                      at(9), at(11), 80, origin=CENTER).to_dict()
    assert plan['stops'] == []
    assert [block['kind'] for block in plan['blocks']] == ['rodando']
    assert any(alert['code'] == 'no_charge_needed' for alert in plan['alerts'])
    assert plan['totals']['charging_cost'] == 0 and plan['totals']['gross_earnings'] > 0
    assert plan['slots'][0]['soc'] == 80 and plan['slots'][-1]['activity'] == 'fim'


def test_occupied_station_adds_queue_and_cheap_off_peak_tariff_is_used():
    busy = option('busy', lat=-23.5506, lng=-46.6334, available=False, status='charging', queue_minutes=30)
    free = option('free', lat=-23.56, lng=-46.64)
    plan = plan_shift(DOLPHIN, prefs(shift_start=10 * 60, shift_end=16 * 60), [busy, free], at(10), at(16), 17,
                      origin=CENTER).to_dict()
    first = plan['stops'][0]
    assert first['start'] == '10:00' and first['station_id'] == 'free'
    tou = option('tou', price=3.0, price_schedule=((14 * 60, 16 * 60, 1.0),))
    plan = plan_shift(DOLPHIN, prefs(shift_start=10 * 60, shift_end=20 * 60), [tou], at(10), at(20), 60,
                      origin=CENTER).to_dict()
    assert plan['stops'] and all('14:00' <= stop['start'] < '16:00' for stop in plan['stops'])
    assert all(stop['price_per_kwh'] == 1.0 for stop in plan['stops'])


def test_plan_is_never_worse_than_naive_and_runs_fast():
    rng = random.Random(7)
    stations = [option(f's{i}', dc=i % 3 == 0, price=rng.uniform(1.2, 2.8),
                       lat=CENTER[0] + rng.uniform(-.1, .1), lng=CENTER[1] + rng.uniform(-.1, .1),
                       amenities=(Amenity('restaurante', 'R', 80),) if i % 5 == 0 else ())
                for i in range(30)]
    preferences = DriverPreferences(shift_start=10 * 60, shift_end=22 * 60)
    worst = 0.0
    for key in ('byd_dolphin', 'renault_kwid_etech', 'byd_seal'):
        for soc in (20, 45, 90):
            started = time.process_time()
            plan = plan_shift(PRESETS[key], preferences, stations, at(10), at(22), soc, origin=CENTER).to_dict()
            worst = max(worst, time.process_time() - started)
            assert plan['totals']['net_profit'] >= plan['baseline']['totals']['net_profit'] - 0.01
            assert plan['totals']['min_soc_percent'] >= 14
    assert worst < 0.6  # alvo de produção: < 200 ms; folga para CI concorrido


def test_next_stop_now_and_keep_driving():
    stations = [option('near', lat=-23.552, lng=-46.634),
                option('cheap', dc=False, price=1.1, lat=-23.58, lng=-46.66)]
    preferences = prefs(shift_start=10 * 60, shift_end=20 * 60)
    urgent = next_stop(DOLPHIN, preferences, stations, at(10, 7), at(20), 16, origin=CENTER)
    assert urgent['recommendation']['action'] == 'stop_now'
    assert urgent['recommendation']['headline'].startswith('Pare agora')
    assert urgent['now'].endswith('10:00:00')
    assert [a['station_id'] for a in urgent['alternatives']] and urgent['alternatives'][0]['distance_km'] is not None
    effective = [a['cost_per_kwh_effective'] for a in urgent['alternatives']]
    assert effective == sorted(effective)
    relaxed = next_stop(DOLPHIN, preferences, stations, at(18), at(20), 90, origin=CENTER)
    assert relaxed['recommendation']['action'] == 'keep_driving'
    assert relaxed['status']['in_peak'] and 'pico' in relaxed['recommendation']['message']


def test_service_shift_window_and_build_from_api_payload():
    preferences = DriverPreferences(shift_start=10 * 60, shift_end=22 * 60)
    assert shift_window(preferences, at(12, 7)) == (at(12), at(22))
    assert shift_window(preferences, at(8)) == (at(10), at(22))
    assert shift_window(preferences, at(23)) == (at(10, day=datetime(2026, 10, 14)), at(22, day=datetime(2026, 10, 14)))
    assert shift_window(preferences, at(12, 7), 'full_shift') == (at(10), at(22))
    overnight = DriverPreferences(shift_start=20 * 60, shift_end=4 * 60, meals=())
    assert shift_window(overnight, at(2)) == (at(2), at(4))
    with pytest.raises(ValueError):
        shift_window(preferences, at(12), 'tomorrow')
    stations = [{'id': 'x', 'name': 'Shopping', 'latitude': -23.56, 'longitude': -46.64,
                 'amenities': [{'kind': 'shopping', 'distance_m': 0}],
                 'connectors': [{'id': 'p', 'connector_type': 'CCS2', 'power_kw': '60', 'price_per_kwh': '2.1',
                                 'available': True, 'online': True, 'availability_status': 'available'}]}]
    profile = validate_profile(merge_profile(None, None))
    payload = {'soc_percent': 40, 'lat': CENTER[0], 'lng': CENTER[1], 'mode': 'full_shift',
               'context': {'rain': True}}
    plan = build_plan(payload, profile, stations, at(9))
    assert plan['mode'] == 'full_shift' and plan['window']['start'] == '10:00'
    assert plan['demand']['source'] == 'heuristica+informado'
    assert plan['stops'] and plan['stops'][0]['station_id'] == 'x'
    quick = build_next_stop({'soc_percent': 40}, profile, stations, at(23, 40))
    assert quick['plan_window']['minutes'] == 4 * 60


# --- revisão de integração (2026-10): regressões ------------------------------------

def test_next_stop_never_says_keep_driving_when_battery_cannot_cover_the_shift():
    preferences = prefs(shift_start=10 * 60, shift_end=20 * 60)
    stations = [option('near', lat=-23.552, lng=-46.634), option('far', lat=-23.60, lng=-46.70)]
    empty = next_stop(DOLPHIN, preferences, stations, at(10, 7), at(20), 0, origin=CENTER)
    recommendation = empty['recommendation']
    assert recommendation['action'] == 'charge_needed'
    assert 'nenhuma recarga' not in recommendation['headline'].lower()
    assert recommendation['station_id'] == 'near'  # posto compatível mais próximo
    assert 'pico' not in recommendation['message']
    almost = next_stop(DOLPHIN, preferences, stations, at(10, 7), at(20), 0.5, origin=CENTER)
    assert almost['recommendation']['action'] in ('stop_now', 'charge_needed')
    no_station = next_stop(DOLPHIN, preferences, [], at(10, 7), at(20), 5, origin=CENTER)
    assert no_station['recommendation']['action'] == 'charge_needed'
    assert 'station_id' not in no_station['recommendation']
    assert any(alert['code'] == 'no_station' for alert in no_station['alerts'])
    full = next_stop(DOLPHIN, preferences, stations, at(10, 7), at(20), 100, origin=CENTER)
    assert full['recommendation']['action'] == 'keep_driving'


def test_next_stop_headline_uses_station_gender():
    stations = [ChargerOption('s', 'Cantina da Vila', -23.552, -46.634, 'ccs2', 60, 2.0, connector_id='s-p')]
    urgent = next_stop(DOLPHIN, prefs(shift_start=10 * 60, shift_end=20 * 60), stations, at(10, 7), at(20), 16,
                       origin=CENTER)
    assert urgent['recommendation']['headline'] == 'Pare agora em Cantina da Vila'


def test_parse_hhmm_rejects_invalid_minutes():
    from chargegrid_core.driver import parse_hhmm
    assert parse_hhmm('10:30') == 630 and parse_hhmm('10h') == 600 and parse_hhmm('24:00') == 0
    for value in ('10:99', '10:60', '25:00', '-1:00', 'ab'):
        with pytest.raises(ValueError):
            parse_hhmm(value)


# --- tela enxuta (2026-10): origem dos valores, clima em uma linha, ganho sem digitar ---------

def test_sources_mark_unconfirmed_defaults_and_legacy_profiles_are_inferred():
    from chargegrid_core.driver import SOURCE_CHOICES
    assert set(SOURCE_CHOICES) == {'earnings_per_hour', 'shift'}
    default = DriverPreferences.from_dict({})
    assert default.to_dict()['sources'] == {'earnings_per_hour': 'estimativa', 'shift': 'auto'}
    assert default.earnings_estimated
    legacy = DriverPreferences.from_dict({'earnings_per_hour': 50, 'shift_start': '06:00', 'shift_end': '14:00'})
    assert legacy.to_dict()['sources'] == {'earnings_per_hour': 'informado', 'shift': 'informado'}
    typed = DriverPreferences.from_dict({'sources': {'earnings_per_hour': 'informado'}})
    assert typed.source('earnings_per_hour') == 'informado' and not typed.earnings_estimated
    # "estimativa" com valor diferente do padrão (app antigo editou o número) vale como informado.
    edited = DriverPreferences.from_dict({'earnings_per_hour': 44, 'sources': {'earnings_per_hour': 'estimativa'}})
    assert edited.source('earnings_per_hour') == 'informado'
    # Leitura tolerante: origem desconhecida é ignorada, nunca derruba um perfil salvo.
    odd = DriverPreferences.from_dict({'sources': {'earnings_per_hour': 'chute', 'x': 'y'}})
    assert odd.source('earnings_per_hour') == 'estimativa'
    assert validate_profile({'preferences': {'sources': 'texto'}})['preferences']['sources']['shift'] == 'auto'


def test_weather_summary_one_line_and_rain_note():
    from chargegrid_core.driver import (
        condition_text,
        rain_note,
        simulated_weather,
        weather_summary,
    )
    assert condition_text(0) == 'céu limpo' and condition_text(81) == 'pancadas de chuva'
    assert condition_text(None) is None and condition_text(1234) is None
    hourly = {at(h): (3.0 if h == 18 else 0.0, 25.0) for h in range(24)}
    signal = WeatherSignal(hourly, codes={at(h): 3 for h in range(24)},
                           current={'temperature': 24.6, 'precipitation': 0.0, 'weather_code': 0, 'time': at(14)})
    summary = weather_summary(signal, at(14, 20))
    assert summary['label'] == '25° · céu limpo · chuva às 18h'
    assert summary['next_rain_at'] == '18:00' and not summary['rain_now'] and summary['status'] == 'ok'
    raining = weather_summary(signal, at(18, 10))
    assert raining['rain_now'] and raining['label'].endswith('mais corridas agora')
    dry = weather_summary(WeatherSignal({at(14): (0.0, None)}), at(14))
    assert dry['label'] == 'sem chuva prevista' and dry['temperature_c'] is None
    assert '18h (Open-Meteo)' in rain_note(signal, at(14))['message']
    assert rain_note(WeatherSignal({at(14): (0.0, 20.0)}), at(14)) is None
    demo = simulated_weather(at(12))
    assert demo.source == 'simulado' and weather_summary(demo, at(12))['label'] == '23° · nublado · chuva às 18h (simulado)'
    assert weather_summary(demo, at(12))['status'] == 'simulado'


def test_earnings_chain_typed_beats_history_beats_estimate():
    from chargegrid_core.driver import (
        EarningsSource,
        Trip,
        TripHistory,
        resolve_earnings,
    )
    trips = (Trip(at(10), at(10, 30), 30.0, 12.0), Trip(at(10, 40), at(11, 0), 20.0, 8.0),
             Trip(at(15), at(15, 30), 25.0, 10.0))
    history = TripHistory(trips)
    assert isinstance(history, EarningsSource)
    assert history.online_minutes() == 90  # 10:00–11:00 (pausa de 10 min conta) + 15:00–15:30
    assert history.hourly() == pytest.approx(50.0)
    assert history.km_per_hour() == pytest.approx(20.0)
    assert TripHistory((Trip(at(10), at(10, 20), 30.0),)).hourly() is None  # menos de 1 h online
    estimate = resolve_earnings(DriverPreferences())
    assert estimate == {'per_hour': 38.0, 'source': 'estimativa', 'estimated': True, 'label': 'R$ 38/h estimado'}
    assert resolve_earnings(DriverPreferences(), history)['source'] == 'uber'
    typed = DriverPreferences(earnings_per_hour=45.5)
    assert resolve_earnings(typed, history) == {'per_hour': 45.5, 'source': 'informado', 'estimated': False,
                                                 'label': 'R$ 45,50/h (seu ganho)'}


def test_context_and_plan_expose_weather_and_earnings_source():
    from chargegrid_core.driver import build_context, simulated_weather
    profile = validate_profile(merge_profile(None, None))
    context = build_context(profile, at(14, 5), (simulated_weather(at(14)),))
    assert context['in_shift'] and context['window'] == {
        'start': '14:00', 'end': '22:00', 'start_at': at(14).isoformat(), 'end_at': at(22).isoformat()}
    assert context['shift_source'] == 'auto' and context['earnings']['estimated']
    assert context['demand']['source'] == 'heuristica+simulado' and context['demand']['level'] == 'normal'
    assert context['demand']['peaks'][0]['start'] == '16:45'
    assert context['weather']['label'].endswith('(simulado)')
    night = build_context(profile, at(23), ())
    assert not night['in_shift'] and night['window']['start'] == '10:00' and night['weather'] is None
    plan = build_plan({'soc_percent': 50, 'mode': 'auto'}, profile, [], at(14), (simulated_weather(at(14)),))
    assert plan['demand']['weather']['status'] == 'simulado' and plan['earnings']['source'] == 'estimativa'
    assert build_plan({'soc_percent': 50}, profile, [], at(14))['demand']['weather'] is None
    quick = build_next_stop({'soc_percent': 50}, profile, [], at(14), (simulated_weather(at(14)),))
    assert quick['demand']['weather']['next_rain_at'] == '18:00'
