import random
from decimal import Decimal as D

from chargegrid_core import balancing as b


def car(identifier, rating='7.2', order=0, **extra):
    return b.Participant(id=identifier, rating_kw=D(rating), order=(order,), **extra)


def targets(decision):
    return {key: item['target_kw'] for key, item in decision['sessions'].items()}


def test_lone_car_gets_full_rating_not_one_nth():
    decision = b.decide([car('a')], site_limit_kw=30, building_load_kw=12)
    assert targets(decision) == {'a': D('7.2')}
    assert decision['sessions']['a']['limited_by'] == b.CHARGER


def test_without_any_limit_each_car_gets_its_request():
    decision = b.decide([car('a'), car('b', '22')])
    assert decision['available_kw'] is None
    assert targets(decision) == {'a': D('7.2'), 'b': D('22')}


def test_available_subtracts_building_load():
    assert b.available(30, 12) == (D(18), b.SITE)
    assert b.available(30, 40) == (D(0), b.SITE)
    assert b.available(30, 12, 10) == (D(10), b.STATION)
    assert b.available(None, None, 15) == (D(15), b.STATION)


def test_three_cars_share_site_and_store_increase_reduces_all():
    cars = [car('a', order=1), car('b', order=2), car('c', order=3)]
    normal = b.decide(cars, site_limit_kw=30, building_load_kw=12)
    assert targets(normal) == {'a': D('6.0'), 'b': D('6.0'), 'c': D('6.0')}
    busy = b.decide(cars, site_limit_kw=30, building_load_kw=24)
    assert targets(busy) == {'a': D('2.0'), 'b': D('2.0'), 'c': D('2.0')}
    assert all(item['limited_by'] == b.SITE for item in busy['sessions'].values())
    assert busy['allocated_kw'] <= busy['available_kw']


def test_two_cars_fit_under_site_and_get_charger_max():
    decision = b.decide([car('a', order=1), car('b', order=2)], site_limit_kw=30, building_load_kw=12)
    assert targets(decision) == {'a': D('7.2'), 'b': D('7.2')}


def test_driver_cap_respected_and_share_is_proportional_to_request():
    roomy = b.decide([car('a', order=1, driver_kw=D('3')), car('b', order=2)], site_limit_kw=30, building_load_kw=12)
    assert targets(roomy) == {'a': D('3'), 'b': D('7.2')}
    assert roomy['sessions']['a']['limited_by'] == b.DRIVER
    tight = b.decide([car('a', order=1, driver_kw=D('3')), car('b', order=2)], site_limit_kw=30, building_load_kw=21)
    assert targets(tight) == {'a': D('2.6'), 'b': D('6.3')}
    assert {item['limited_by'] for item in tight['sessions'].values()} == {b.SITE}


def test_newest_paused_when_capacity_below_floors():
    cars = [car('a', order=1), car('b', order=2), car('c', order=3)]
    decision = b.decide(cars, site_limit_kw=30, building_load_kw=27)
    assert targets(decision) == {'a': D('1.5'), 'b': D('1.5'), 'c': D(0)}
    assert decision['sessions']['c']['limited_by'] == b.PAUSED
    assert decision['allocated_kw'] <= D(3)


def test_store_above_limit_pauses_everyone():
    decision = b.decide([car('a'), car('b', order=1)], site_limit_kw=30, building_load_kw=31)
    assert targets(decision) == {'a': D(0), 'b': D(0)}


def test_three_phase_floor_is_device_floor():
    cars = [car('a', '11', order=1, floor_kw=D('4.2')), car('b', '11', order=2, floor_kw=D('4.2'))]
    decision = b.decide(cars, site_limit_kw=30, building_load_kw=24)
    assert targets(decision) == {'a': D('6.0'), 'b': D(0)}


def test_legacy_device_is_fixed_load():
    cars = [car('old', order=1, adjustable=False, fixed_kw=D('7.2')), car('new', order=2)]
    decision = b.decide(cars, site_limit_kw=30, building_load_kw=18)
    assert targets(decision) == {'old': D('7.2'), 'new': D('4.8')}
    assert decision['sessions']['old']['limited_by'] == b.FIXED


def test_step_reduces_first_and_raises_only_into_confirmed_headroom():
    assert b.step(D('6'), D('7.2'), D('14.4'), D(18)) == ('reduce', D('6'))
    # Os outros ainda não confirmaram a redução: nada de aumento.
    assert b.step(D('6'), D(0), D('14.4'), D(18), D('1.4')) == ('raise', D('3.6'))
    assert b.step(D('6'), D(0), D('17'), D(18), D('1.4')) is None
    # Depois dos ACKs, sobe até o alvo.
    assert b.step(D('6'), D('3.6'), D('12'), D(18)) == ('raise', D('6'))
    assert b.step(D('6'), D('6'), D('12'), D(18)) is None
    assert b.step(D('6'), D(0), D(0), None) == ('raise', D('6'))


def test_pending_increase_counts_in_envelope_of_others():
    envelopes = {'a': D('7.2'), 'b': D('7.2')}  # b tem aumento pendente para 7,2
    assert b.step(D('6'), D(0), sum(envelopes.values()), D(18)) == ('raise', D('3.6'))


def test_exceeded_measures_transient_overload():
    assert b.exceeded([D('6'), D('6'), D('6')], D(6)) == D(12)
    assert b.exceeded([D('2'), D('2')], D(6)) == 0
    assert b.exceeded([D('9')], None) == 0


def test_explain_texts_ptbr():
    decision = b.decide([car('a', '22', order=1), car('b', '22', order=2)], site_limit_kw=60, building_load_kw='45.6')
    reason = b.explain(decision, 'a')
    assert reason['code'] == b.SITE
    assert reason['text'] == '7,2 kW porque a loja usa 45,6 de 60 kW e há 2 carros carregando.'
    assert reason['short'] == 'Loja 45,6/60 kW · 2 carros'
    wide = b.decide([car('a', '22', order=1), car('b', '22', order=2)], site_limit_kw=60, building_load_kw=38)
    assert b.explain(wide, 'b')['text'] == '11 kW porque a loja usa 38 de 60 kW e há 2 carros carregando.'
    alone = b.explain(b.decide([car('a')], site_limit_kw=30, building_load_kw=26), 'a')
    assert alone['text'] == '4 kW porque a loja usa 26 de 30 kW e só o seu carro está carregando.'
    full = b.explain(b.decide([car('a')], site_limit_kw=30, building_load_kw=12), 'a')
    assert full['text'] == '7,2 kW, o máximo deste carregador (a loja usa 12 de 30 kW; 1 carro carregando).'
    paused = b.decide([car('a', order=1), car('b', order=2), car('c', order=3)], site_limit_kw=30, building_load_kw=27)
    assert b.explain(paused, 'c')['text'].startswith('Pausado: a loja usa 27 de 30 kW')
    cap = b.decide([car('a', order=1), car('b', order=2)], station_cap_kw=10)
    assert b.explain(cap, 'a')['text'] == '5 kW porque o posto limita os carregadores a 10 kW e há 2 carros carregando.'


def test_short_reason_fits_physical_panel():
    cases = [
        b.decide([car(str(i), order=i) for i in range(12)], site_limit_kw='9999.9', building_load_kw='9000.5'),
        b.decide([car('a', adjustable=False)], site_limit_kw=30, building_load_kw=1),
        b.decide([car('a', order=1), car('b', order=2)], station_cap_kw=3),
    ]
    for decision in cases:
        for key in decision['sessions']:
            short = b.explain(decision, key)['short']
            assert len(short) <= 40
            short.encode('latin-1')


def test_snapshot_trigger_and_fingerprint():
    first = b.snapshot(b.decide([car('a')], site_limit_kw=30, building_load_kw=12), {'a': D('7.2')})
    assert b.trigger(None, first) == 'initial'
    store = b.snapshot(b.decide([car('a')], site_limit_kw=30, building_load_kw=24), {'a': D('7.2')})
    assert b.trigger(first, store) == 'building_load_changed'
    two = b.snapshot(b.decide([car('a'), car('b', order=1)], site_limit_kw=30, building_load_kw=12), {'a': D('7.2')})
    assert b.trigger(first, two) == 'session_started'
    assert b.trigger(two, first) == 'session_ended'
    acked = b.snapshot(b.decide([car('a')], site_limit_kw=30, building_load_kw=12), {'a': D('6')})
    assert b.trigger(first, acked) == 'power_confirmed'
    assert b.fingerprint(first) == b.fingerprint(dict(first))
    assert b.fingerprint(first) != b.fingerprint(acked)


def test_summary_lists_points():
    decision = b.decide([car('a', order=1), car('b', order=2)], site_limit_kw=30, building_load_kw=24)
    assert b.summary(decision, {'a': 'CG-A', 'b': 'CG-B'}) == \
        'Disponível 6 kW (loja usa 24 de 30 kW) para 2 carros: CG-A 3 kW, CG-B 3 kW.'


def test_random_event_sequences_never_raise_past_available():
    """Propriedade: um aumento nunca leva Σ envelopes acima do disponível."""
    rng = random.Random(7)
    for _ in range(300):
        applied, pending, order = {}, {}, 0
        building = D(rng.randint(0, 25))
        for _ in range(40):
            event = rng.choice(['add', 'remove', 'load', 'ack', 'tick', 'tick'])
            if event == 'add' and len(applied) < 4:
                order += 1
                applied[f'c{order}'] = D(0)
            elif event == 'remove' and applied:
                key = rng.choice(sorted(applied))
                applied.pop(key)
                pending.pop(key, None)
            elif event == 'load':
                building = D(rng.randint(0, 32))
            elif event == 'ack' and pending:
                key = rng.choice(sorted(pending))
                applied[key] = pending.pop(key)
            cars = [car(key, order=int(key[1:])) for key in applied]
            decision = b.decide(cars, site_limit_kw=30, building_load_kw=building)
            avail = decision['available_kw']
            for key in sorted(applied):
                if key in pending:
                    continue
                envelopes = {k: max(applied[k], pending.get(k, D(0))) for k in applied}
                others = sum(v for k, v in envelopes.items() if k != key)
                action = b.step(decision['sessions'][key]['target_kw'], applied[key], others, avail)
                if action is None:
                    continue
                kind, value = action
                pending[key] = value
                if kind == 'raise':
                    total = sum(max(applied[k], pending.get(k, D(0))) for k in applied)
                    assert total <= avail, (building, applied, pending)
