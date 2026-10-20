"""Cartões de previsão: "Melhor horário" (motorista) e previsão de ocupação (vendedor).

Os números vêm prontos da API (``/v1/stations/{id}/best-times`` e ``/v1/owner/forecast``)
ou da conta demo, que usa o mesmo ``chargegrid_core.forecast``.
"""

from datetime import datetime

import flet as ft

from chargegrid_core.formatting import brl

from . import design as D
from . import theme

GREEN = '#3EBF80'
AMBER = '#E8922B'
BAR_EMPTY = '#2E2E2E'
SYNTHETIC_LABEL = 'Inclui histórico sintético'


def _hour(value) -> str:
    try:
        return f'{datetime.fromisoformat(str(value)).hour}h'
    except (TypeError, ValueError):
        return ''


def _moment(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def window_text(start, end) -> str:
    first, last = _hour(start), _hour(end)
    return f'{first}–{"24h" if last == "0h" else last}'


def _num(value, digits=1) -> str:
    try:
        return f'{float(value):.{digits}f}'.replace('.', ',')
    except (TypeError, ValueError):
        return '—'


def synthetic_note(payload):
    if not payload.get('includes_synthetic'):
        return []
    return [ft.Row([ft.Icon(ft.Icons.SCIENCE_OUTLINED, size=15, color=theme.WARNING),
                    D.txt(SYNTHETIC_LABEL + ' (rotulado, para demonstração).', 11, 'regular', theme.WARNING,
                          expand=True)], spacing=6)]


def price_bars(hours, best_start, best_end=None):
    """Uma barra por hora: altura pelo preço esperado; a melhor janela em verde."""
    window = (_moment(best_start), _moment(best_end) if best_end else None)
    prices = []
    for item in hours:
        try:
            prices.append(float(item['expected_price_per_kwh']))
        except (KeyError, TypeError, ValueError):
            prices.append(0.0)
    top, low = max(prices, default=0) or 1, min(prices, default=0)
    bars = []
    for item, price in zip(hours, prices, strict=True):
        moment = _moment(item.get('start'))
        best = (moment is not None and window[0] is not None and
                (moment == window[0] if window[1] is None else window[0] <= moment < window[1]))
        height = 14 + 22 * ((price - low) / (top - low) if top > low else 0.5)
        bars.append(ft.Column([ft.Container(width=14, height=height, border_radius=4,
                                            bgcolor=GREEN if best else BAR_EMPTY),
                               D.txt(_hour(item.get('start')), 8.5, 'regular', theme.GRAY_TEXT)],
                              spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              alignment=ft.MainAxisAlignment.END))
    return ft.Row(bars, spacing=4, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                  vertical_alignment=ft.CrossAxisAlignment.END, scroll=ft.ScrollMode.AUTO)


def best_time_card(payload):
    """Cartão "Melhor horário para carregar" ou ``None`` quando não há o que mostrar."""
    best = payload.get('best') if isinstance(payload, dict) else None
    if not best:
        return None
    saving = best.get('saving_vs_now_percent')
    headline = f"{window_text(best['start'], best['end'])} · a partir de {brl(best['price_from'])}/kWh"
    detail = best.get('reason') or ''
    if saving:
        detail = f'{saving}% mais barato que agora · {detail}'
    elif payload.get('stable') and best.get('level_label'):
        detail = f"{detail} · {best['level_label'].lower()}"
    content = [
        ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=18, color=GREEN),
                D.txt('Melhor horário para carregar', 13.5, 'semibold', expand=True)], spacing=8),
        D.txt(headline, 16, 'bold'),
        D.txt(detail, 11.5, 'regular', theme.GRAY_TEXT),
        price_bars(payload.get('hours') or [], best.get('start'), best.get('end')),
        D.txt(payload.get('note') or 'Estimativa.', 10.5, 'regular', theme.GRAY_TEXT),
        *synthetic_note(payload),
    ]
    return ft.Container(ft.Column(content, spacing=8), bgcolor=theme.CARD, border_radius=D.RADIUS_CARD,
                        padding=ft.Padding(left=14, right=14, top=13, bottom=13), data='best-time')


def method_label(method) -> str:
    return 'Modelo (gradient boosting)' if method == 'gbm' else 'Média do mesmo dia e hora'


def occupancy_bars(hours, count=24):
    """Ocupação prevista por hora (barras), laranja quando deve lotar."""
    bars = []
    for index, item in enumerate(hours[:count]):
        try:
            value = float(item['occupancy_percent'])
        except (KeyError, TypeError, ValueError):
            value = 0.0
        bars.append(ft.Column([ft.Container(width=10, height=4 + 0.56 * value, border_radius=3,
                                            bgcolor=AMBER if item.get('full') else GREEN),
                               D.txt(_hour(item.get('start')) if index % 3 == 0 else '', 8, 'regular',
                                     theme.GRAY_TEXT)],
                              spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              alignment=ft.MainAxisAlignment.END))
    return ft.Row(bars, spacing=3, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                  vertical_alignment=ft.CrossAxisAlignment.END, height=80)


def accuracy_lines(payload):
    """Textos curtos com o acerto medido (modelo × média), sem exagero."""
    accuracy = payload.get('accuracy') or {}
    base, model = accuracy.get('baseline') or {}, accuracy.get('gbm') or {}
    daily = accuracy.get('daily') or {}
    lines = []
    if base.get('mae_pp') is not None:
        text = f"Erro por hora: {_num(base['mae_pp'])} p.p. (média)"
        if model.get('mae_pp') is not None:
            text += f" × {_num(model['mae_pp'])} p.p. (modelo)"
        lines.append(text)
    chosen = daily.get(payload.get('method')) or daily.get('baseline') or {}
    if chosen.get('peak_hit_percent') is not None:
        lines.append(f"Acerto do horário de pico: {_num(chosen['peak_hit_percent'], 0)}%")
    energy = (daily.get('baseline') or {}).get('energy_day_accuracy_percent')
    if energy is not None:
        lines.append(f'Acerto da energia do dia: {_num(energy, 0)}%')
    if accuracy.get('origins'):
        lines.append(f"Medido em {accuracy['origins']} dias, refazendo cada previsão só com dados anteriores.")
    return lines


def forecast_summary_card(payload, on_click=None):
    """Resumo para a página de consumo de energia do vendedor."""
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        reason = (payload or {}).get('method_reason') if isinstance(payload, dict) else None
        body = [D.txt('Previsão de ocupação', 13, 'bold'),
                D.txt(reason or 'Ainda sem histórico para prever.', 11.5, 'regular', theme.GRAY_TEXT)]
    else:
        peaks = payload.get('peaks') or []
        headline = peaks[0]['label'] if peaks else 'Sem lotação prevista nas próximas 36 h'
        body = [ft.Row([D.txt('Previsão de ocupação', 13, 'bold', expand=True),
                        D.txt(method_label(payload.get('method')), 10.5, 'regular', theme.GRAY_TEXT)]),
                D.txt(headline, 15, 'bold', AMBER if peaks else GREEN),
                occupancy_bars(payload.get('hours') or []),
                *[D.txt(line, 11, 'regular', theme.GRAY_TEXT) for line in accuracy_lines(payload)[:1]],
                *synthetic_note(payload)]
    if on_click:
        body.append(D.txt('Ver previsão e sugestões', 12, 'semibold', GREEN))
    return ft.Container(ft.Column(body, spacing=8), bgcolor=theme.CARD, border_radius=D.RADIUS_CARD,
                        padding=ft.Padding(left=15, right=15, top=14, bottom=14), on_click=on_click,
                        ink=bool(on_click), data='forecast-summary')
