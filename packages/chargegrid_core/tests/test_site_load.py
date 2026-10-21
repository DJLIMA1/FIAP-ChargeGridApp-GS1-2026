from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import pairwise

import pytest

from chargegrid_core import balancing, site_load

UTC = timezone.utc


def brt(year, month, day, hour, minute=0):
    """Hora local de Brasília (UTC−3) em UTC."""
    return datetime(year, month, day, hour + 3, minute, tzinfo=UTC) if hour + 3 < 24 else \
        datetime(year, month, day, hour - 21, minute, tzinfo=UTC) + timedelta(days=1)


TUESDAY = (2026, 10, 20)
SUNDAY = (2026, 10, 25)


def test_catalog_covers_the_researched_establishments():
    assert set(site_load.PROFILES) == {'conveniencia', 'farmacia', 'padaria', 'supermercado', 'restaurante',
                                       'shopping'}
    for profile in site_load.PROFILES.values():
        for curve in (profile.weekday, profile.saturday, profile.sunday or profile.saturday):
            assert len(curve) == 24 and all(0 < value <= 1 for value in curve)
        assert max(profile.weekday) == 1  # o pico do dia útil é o pico do tipo
    assert site_load.SOURCES and all('http' in source for source in site_load.SOURCES)


def test_default_contracted_limit_follows_group_b_and_margin():
    # Comércio pequeno cabe no Grupo B (até 75 kW de carga instalada).
    for key in ('conveniencia', 'farmacia', 'padaria', 'restaurante'):
        assert site_load.default_site_limit_kw(key) == Decimal(75)
    # Grupo A: pico × 1,3 arredondado para cima de 10 em 10 kW.
    assert site_load.default_site_limit_kw('supermercado') == Decimal(130)
    assert site_load.default_site_limit_kw('padaria', 'grande') == Decimal(100)
    assert site_load.default_site_limit_kw('shopping') == Decimal(980)
    assert site_load.default_site_limit_kw(None, None) == Decimal(75)  # padrão: posto com conveniência
    assert site_load.default_site_limit_kw('???', 'xx') == Decimal(75)
    assert site_load.effective_site_limit(None, 'supermercado') == (Decimal(130), True)
    assert site_load.effective_site_limit('42.5', 'supermercado') == (Decimal('42.5'), False)


def test_curve_shapes_match_the_research():
    day = TUESDAY
    frac = site_load.curve_fraction
    # Conveniência 24 h: base alta (refrigeração) e pico à tarde.
    assert frac('conveniencia', brt(*day, 3)) > 0.55
    assert frac('conveniencia', brt(*day, 15)) > frac('conveniencia', brt(*day, 3)) + 0.3
    # Restaurante: almoço e jantar acima do meio da tarde e da madrugada.
    assert frac('restaurante', brt(*day, 12)) > frac('restaurante', brt(*day, 16)) + 0.4
    assert frac('restaurante', brt(*day, 20)) > frac('restaurante', brt(*day, 16)) + 0.3
    assert frac('restaurante', brt(*day, 3)) < 0.25
    # Padaria: forno de manhã cedo.
    assert frac('padaria', brt(*day, 6)) == pytest.approx(1.0)
    assert frac('padaria', brt(*day, 6)) > frac('padaria', brt(*day, 13))
    # Supermercado: refrigeração 24 h mantém mais da metade do pico de madrugada.
    assert frac('supermercado', brt(*day, 3)) > 0.5
    # Farmácia e shopping fechados de madrugada.
    assert frac('farmacia', brt(*day, 3)) < 0.3 and frac('shopping', brt(*day, 3)) < 0.3


def test_weekday_versus_weekend():
    frac = site_load.curve_fraction
    # Shopping abre mais tarde no domingo.
    assert frac('shopping', brt(*SUNDAY, 10)) < frac('shopping', brt(*TUESDAY, 10)) - 0.3
    # Farmácia: domingo mais fraco que o dia útil à tarde.
    assert frac('farmacia', brt(*SUNDAY, 15)) < frac('farmacia', brt(*TUESDAY, 15))


def test_curve_is_interpolated_between_hours():
    start, end = brt(*TUESDAY, 10), brt(*TUESDAY, 11)
    middle = brt(*TUESDAY, 10, 30)
    expected = (site_load.curve_fraction('restaurante', start) + site_load.curve_fraction('restaurante', end)) / 2
    assert site_load.curve_fraction('restaurante', middle) == pytest.approx(expected)


def test_air_conditioning_makes_summer_heavier():
    february = datetime(2026, 2, 4, 18, tzinfo=UTC)
    july = datetime(2026, 7, 29, 18, tzinfo=UTC)
    assert site_load.season_factor('shopping', february) == pytest.approx(1.0, abs=0.01)
    assert site_load.season_factor('shopping', july) < 0.86
    # Quem depende menos de climatização (padaria) varia menos.
    assert site_load.season_factor('padaria', july) > site_load.season_factor('shopping', july)


def test_simulation_is_reproducible_per_station_and_window():
    moment = brt(*TUESDAY, 15, 2)
    first = site_load.simulate('station-a', moment)
    assert site_load.simulate('station-a', moment) == first
    # Constante dentro da janela de 5 min.
    assert site_load.simulate('station-a', brt(*TUESDAY, 15, 4)) == first
    assert site_load.window_start(moment) == brt(*TUESDAY, 15, 0)
    # Postos diferentes variam de forma diferente ao longo do dia.
    day = [brt(*TUESDAY, 0) + timedelta(minutes=5 * index) for index in range(288)]
    a = [site_load.simulate('station-a', at) for at in day]
    b = [site_load.simulate('station-b', at) for at in day]
    assert a != b
    # Sem fuso = UTC.
    naive = moment.replace(tzinfo=None)
    assert site_load.simulate('station-a', naive) == first


def test_variation_is_smooth_and_bounded():
    day = [brt(*TUESDAY, 0) + timedelta(minutes=5 * index) for index in range(288 * 7)]
    peak = site_load.peak_kw('conveniencia')
    values = [site_load.simulate('station-a', at, 'conveniencia') for at in day]
    assert all(value >= 0 for value in values)
    assert max(values) <= peak * Decimal('1.13')
    steps = [abs(after - before) for before, after in pairwise(values)]
    assert max(steps) <= peak * Decimal('0.03')  # sem saltos entre janelas
    assert len(set(values)) > 50  # varia de verdade
    factors = [site_load.variation('station-a', at) for at in day]
    assert 0.87 < min(factors) and max(factors) < 1.13


@pytest.mark.parametrize('profile', sorted(site_load.PROFILES))
def test_size_scales_the_load(profile):
    moment = brt(*TUESDAY, 14)
    small = site_load.simulate('s', moment, profile, 'pequeno')
    large = site_load.simulate('s', moment, profile, 'grande')
    assert small < site_load.simulate('s', moment, profile, 'medio') < large


def test_load_never_passes_85_percent_of_the_limit():
    moment = brt(*TUESDAY, 15)
    assert site_load.simulate('s', moment, 'supermercado', site_limit_kw=Decimal(40)) == Decimal('34.0')
    assert site_load.ceiling_kw(None) is None
    assert site_load.simulate('s', moment, 'supermercado') > Decimal(40)


def test_store_plus_chargers_never_exceed_the_contracted_limit():
    cars = [balancing.Participant(id=f'car-{index}', rating_kw=Decimal(rating), order=(index,))
            for index, rating in enumerate(('60', '22', '22', '7.4'))]
    for profile in site_load.PROFILES:
        for size in site_load.SIZES:
            limit = site_load.default_site_limit_kw(profile, size)
            for hour in range(0, 24 * 7, 3):
                moment = brt(*TUESDAY, 0) + timedelta(hours=hour, minutes=7)
                load = site_load.simulate('station-x', moment, profile, size, site_limit_kw=limit)
                decision = balancing.decide(cars, site_limit_kw=limit, building_load_kw=load)
                assert load + decision['allocated_kw'] <= limit
                assert decision['available_kw'] >= limit - site_load.ceiling_kw(limit)  # sempre sobra para um carro


def test_labels():
    assert site_load.profile_label() == 'Loja de conveniência · porte médio'
    assert site_load.profile_label('padaria', 'grande') == 'Padaria · porte grande'
    assert site_load.LABEL == 'SIMULADO'
