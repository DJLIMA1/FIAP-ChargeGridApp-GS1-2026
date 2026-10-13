"""Estimativa de energia, tempo e custo de recarga (sempre nominal e aproximada)."""

from __future__ import annotations

TAPER_FROM_PERCENT = 80.0  # acima disso a potência cai (curva simplificada)
TAPER_FACTOR = 0.5
EFFICIENCY = 0.9


class EstimateError(ValueError):
    pass


def estimate_charge(power_kw: float, price_per_kwh: float, *, energy_kwh: float | None = None,
                    minutes: float | None = None, battery_kwh: float | None = None,
                    from_percent: float | None = None, to_percent: float | None = None,
                    budget_brl: float | None = None, max_minutes: float | None = None) -> dict:
    """Retorna {'energy_kwh','minutes','cost_brl','assumptions'} a partir de um dos alvos.

    Ordem de prioridade: energia explícita, faixa de SoC (com bateria), orçamento, tempo.
    """
    if not power_kw or power_kw <= 0 or price_per_kwh is None or price_per_kwh < 0:
        raise EstimateError("potência e tarifa do ponto são necessárias")
    assumptions = ["Potência nominal do ponto; o veículo pode aceitar menos.",
                   f"Eficiência de {EFFICIENCY:.0%} e redução de potência acima de {TAPER_FROM_PERCENT:.0f}%."]
    effective = power_kw * EFFICIENCY
    taper_kwh = 0.0
    if energy_kwh is None and battery_kwh and from_percent is not None and to_percent is not None:
        if not 0 <= from_percent < to_percent <= 100:
            raise EstimateError("faixa de bateria inválida")
        energy_kwh = battery_kwh * (to_percent - from_percent) / 100
        taper_kwh = battery_kwh * max(0.0, to_percent - max(from_percent, TAPER_FROM_PERCENT)) / 100
    if energy_kwh is None and budget_brl is not None:
        if price_per_kwh <= 0:
            raise EstimateError("ponto gratuito: informe tempo ou energia")
        energy_kwh = budget_brl / price_per_kwh
    if energy_kwh is None and minutes is not None:
        energy_kwh = effective * minutes / 60
    if energy_kwh is None or energy_kwh <= 0:
        raise EstimateError("informe energia, faixa de bateria, orçamento ou tempo")
    normal_kwh = energy_kwh - taper_kwh
    hours = normal_kwh / effective + taper_kwh / (effective * TAPER_FACTOR)
    total_minutes = hours * 60
    if max_minutes and total_minutes > max_minutes:
        assumptions.append(f"Limitado ao tempo máximo do ponto ({int(max_minutes)} min).")
        energy_kwh = energy_kwh * max_minutes / total_minutes
        total_minutes = float(max_minutes)
    return {"energy_kwh": round(energy_kwh, 2), "minutes": round(total_minutes),
            "cost_brl": round(energy_kwh * price_per_kwh, 2), "assumptions": assumptions}
