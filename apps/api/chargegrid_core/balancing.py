"""Rebalanceamento de potência ao vivo entre as recargas de um posto.

Regra pura, sem banco nem rede, compartilhada pela API (decisão e comandos) e
pelos testes. Tudo em ``Decimal`` e kW, em passos de 0,1 kW.

Disponível para os carregadores
-------------------------------
``min(teto dos carregadores do posto, limite contratado − consumo do estabelecimento)``,
nunca abaixo de zero. Sem nenhum dos dois configurado, não há limite: cada carro
recebe o próprio máximo.

Divisão
-------
1. Participam as sessões que estão carregando (``starting``/``charging``), não os
   conectores publicados: um carro sozinho recebe o próprio máximo, não 1/N.
2. Pedido de cada sessão = ``min(nominal, limite do conector, limite do motorista,
   máximo do equipamento)``.
3. Equipamento sem ajuste ao vivo (firmware antigo) é carga fixa: consome a potência
   com que começou e sai da divisão.
4. O restante é dividido com ``power.share`` (proporcional ao pedido, piso por
   equipamento: 1,4 kW na bancada, 4,2 kW num carregador trifásico).
5. Se o restante não cobre o piso de todos, os carros que chegaram antes são
   atendidos primeiro e os mais novos ficam pausados (0 kW).

Transição segura
----------------
O envelope de um ponto é o maior valor que ainda pode estar aplicado nele (aplicado
confirmado ou ajuste pendente). Reduções são emitidas sempre; um aumento só cabe na
folga ``disponível − Σ envelopes dos outros − aplicado``. Assim a soma nunca passa do
disponível por causa de um aumento; um salto do consumo da loja pode passar até as
reduções serem confirmadas, e isso é medido em ``exceeded``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from .power import FLOOR_KW, STEP, kw_text, share, to_kw

ZERO = Decimal(0)

PAUSED = 'paused'
FIXED = 'fixed'
SITE = 'site'
STATION = 'station'
CHARGER = 'charger'
PORT = 'port'
DRIVER = 'driver'
DEVICE = 'device'

_TIE_ORDER = {CHARGER: 0, PORT: 1, DEVICE: 2, DRIVER: 3}


def _kw(value) -> Decimal | None:
    number = to_kw(value)
    return None if number is None else number


def _down(value: Decimal) -> Decimal:
    return value.quantize(STEP, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class Participant:
    """Uma sessão que disputa a potência do posto (valores em kW)."""

    id: str
    rating_kw: Decimal
    port_limit_kw: Decimal | None = None
    driver_kw: Decimal | None = None
    device_max_kw: Decimal | None = None
    floor_kw: Decimal = FLOOR_KW
    adjustable: bool = True
    fixed_kw: Decimal | None = None
    order: tuple = ()

    def request(self) -> tuple[Decimal, str]:
        """Pedido da sessão e quem o limita (``charger``/``port``/``device``/``driver``)."""
        candidates = [(CHARGER, _kw(self.rating_kw) or ZERO)]
        for kind, value in ((PORT, self.port_limit_kw), (DEVICE, self.device_max_kw), (DRIVER, self.driver_kw)):
            value = _kw(value)
            if value is not None and value > 0:
                candidates.append((kind, value))
        kind, value = min(candidates, key=lambda item: (item[1], _TIE_ORDER[item[0]]))
        return max(ZERO, value), kind


def available(site_limit_kw=None, building_load_kw=None, station_cap_kw=None) -> tuple[Decimal | None, str | None]:
    """Potência disponível para os carregadores e quem a limita (``site``/``station``)."""
    site_limit = _kw(site_limit_kw)
    cap = _kw(station_cap_kw)
    site = None if site_limit is None else max(ZERO, site_limit - (_kw(building_load_kw) or ZERO))
    if site is None and cap is None:
        return None, None
    if site is None:
        return cap, STATION
    if cap is None or site <= cap:
        return site, SITE
    return cap, STATION


def decide(participants, *, site_limit_kw=None, building_load_kw=None, station_cap_kw=None) -> dict:
    """Alvo de cada sessão. Devolve ``{available_kw, binding, cars, allocated_kw, sessions:
    {id: {target_kw, request_kw, floor_kw, limited_by}}, ...entradas}``."""
    avail, binding = available(site_limit_kw, building_load_kw, station_cap_kw)
    ordered = sorted(participants, key=lambda item: (tuple(item.order), item.id))
    sessions = {}
    fixed_total = ZERO
    requests = {}
    for item in ordered:
        requests[item.id] = item.request()
        if not item.adjustable:
            value = _kw(item.fixed_kw)
            value = requests[item.id][0] if value is None else value
            sessions[item.id] = {'target_kw': value, 'request_kw': requests[item.id][0],
                                 'floor_kw': item.floor_kw, 'limited_by': FIXED}
            fixed_total += value
    adjustable = [item for item in ordered if item.adjustable]
    if avail is None:
        for item in adjustable:
            request, kind = requests[item.id]
            sessions[item.id] = {'target_kw': request, 'request_kw': request, 'floor_kw': item.floor_kw,
                                 'limited_by': kind}
    else:
        remaining = max(ZERO, avail - fixed_total)
        chosen, used = [], ZERO
        for item in adjustable:
            floor = min(_kw(item.floor_kw) or FLOOR_KW, requests[item.id][0])
            if used + floor > remaining:
                break  # Ordem de chegada: quem chegou depois não fura a fila.
            chosen.append(item)
            used += floor
        shares = share({item.id: requests[item.id][0] for item in chosen}, remaining,
                       {item.id: item.floor_kw for item in chosen})
        for item in adjustable:
            request, kind = requests[item.id]
            if item.id in shares:
                target = shares[item.id]
                limited_by = binding if target < request else kind
            else:
                target, limited_by = ZERO, PAUSED
            sessions[item.id] = {'target_kw': target, 'request_kw': request, 'floor_kw': item.floor_kw,
                                 'limited_by': limited_by}
    return {
        'available_kw': avail,
        'binding': binding,
        'site_limit_kw': _kw(site_limit_kw),
        'building_load_kw': _kw(building_load_kw) if site_limit_kw is not None else None,
        'station_cap_kw': _kw(station_cap_kw),
        'cars': len(ordered),
        'allocated_kw': sum((value['target_kw'] for value in sessions.values()), ZERO),
        'sessions': sessions,
    }


def step(target_kw, applied_kw, others_envelope_kw, available_kw, floor_kw=FLOOR_KW):
    """Próximo ajuste seguro de um ponto: ``('reduce', kW)``, ``('raise', kW)`` ou ``None``.

    Reduções saem sempre. Um aumento só usa a folga confirmada; abaixo do piso o ponto
    continua como está (pausado, se estava em 0) até sobrar o mínimo.
    """
    target = _kw(target_kw) or ZERO
    applied = _kw(applied_kw) or ZERO
    if target < applied:
        return ('reduce', target)
    if target == applied:
        return None
    if available_kw is None:
        return ('raise', target)
    headroom = max(ZERO, _kw(available_kw) - (_kw(others_envelope_kw) or ZERO) - applied)
    raise_to = _down(min(target, applied + headroom))
    if raise_to <= applied or raise_to < min(_kw(floor_kw) or FLOOR_KW, target):
        return None
    return ('raise', raise_to)


def exceeded(envelopes_kw, available_kw) -> Decimal:
    """Quanto a soma dos envelopes passa do disponível (0 quando cabe ou não há limite)."""
    if available_kw is None:
        return ZERO
    return max(ZERO, sum((_kw(value) or ZERO for value in envelopes_kw), ZERO) - _kw(available_kw))


def _cars(count: int) -> str:
    return '1 carro' if count == 1 else f'{count} carros'


def explain(decision: dict, session_id) -> dict:
    """Motivo da potência de uma sessão: ``{code, text, short}``.

    ``text`` é a frase em pt-BR mostrada no app, no painel do vendedor e no recibo;
    ``short`` cabe no painel físico (Latin-1, até 40 caracteres).
    """
    item = decision['sessions'][session_id]
    code = item['limited_by']
    kw = kw_text(item['target_kw'])
    count = decision['cars']
    building = kw_text(decision.get('building_load_kw') or ZERO)
    limit = kw_text(decision.get('site_limit_kw'))
    cap = kw_text(decision.get('station_cap_kw'))
    site_known = decision.get('site_limit_kw') is not None
    alone = 'só o seu carro está carregando' if count == 1 else f'há {count} carros carregando'
    context = f' (a loja usa {building} de {limit} kW; {_cars(count)} carregando).' if site_known else '.'
    if code == SITE:
        text = f'{kw} kW porque a loja usa {building} de {limit} kW e {alone}.'
        short = f'Loja {building}/{limit} kW · {_cars(count)}'
    elif code == STATION:
        text = f'{kw} kW porque o posto limita os carregadores a {cap} kW e {alone}.'
        short = f'Posto {cap} kW · {_cars(count)}'
    elif code == PAUSED:
        floor = kw_text(item.get('floor_kw') or FLOOR_KW)
        if decision.get('binding') == SITE:
            text = (f'Pausado: a loja usa {building} de {limit} kW e não sobra o mínimo de {floor} kW '
                    'para mais um carro.')
        else:
            text = f'Pausado: o limite de {cap} kW do posto já está com os carros que chegaram antes.'
        short = 'Pausado: sem capacidade'
    elif code == FIXED:
        text = f'{kw} kW fixos: este equipamento não ajusta a potência durante a recarga.'
        short = 'Potência fixa'
    elif code == PORT:
        text = f'{kw} kW, o limite que o vendedor definiu para este conector.'
        short = 'Limite do conector'
    elif code == DRIVER:
        text = f'{kw} kW, o limite escolhido para o seu carro.'
        short = 'Limite do carro'
    elif code == DEVICE:
        text = f'{kw} kW, o máximo deste equipamento{context}'
        short = 'Máx. do equipamento'
    else:
        text = f'{kw} kW, o máximo deste carregador{context}'
        short = 'Máx. do carregador'
        code = CHARGER
    return {'code': code, 'text': text, 'short': short[:40]}


def summary(decision: dict, labels: dict | None = None) -> str:
    """Resumo da decisão do posto para o registro (até 300 caracteres)."""
    labels = labels or {}
    avail = decision['available_kw']
    if avail is None:
        head = 'Sem limite configurado: cada carro recebe o próprio máximo'
    elif decision['binding'] == SITE:
        head = (f"Disponível {kw_text(avail)} kW (loja usa {kw_text(decision['building_load_kw'] or ZERO)} "
                f"de {kw_text(decision['site_limit_kw'])} kW)")
    else:
        head = f'Disponível {kw_text(avail)} kW (teto dos carregadores do posto)'
    parts = []
    for key, item in decision['sessions'].items():
        name = labels.get(key, str(key)[:8])
        value = 'pausado' if item['limited_by'] == PAUSED else f"{kw_text(item['target_kw'])} kW"
        parts.append(f'{name} {value}')
    text = f"{head} para {_cars(decision['cars'])}" + (': ' + ', '.join(parts) if parts else '') + '.'
    return text[:300]


def _text(value):
    return None if value is None else str(value)


def snapshot(decision: dict, envelopes: dict | None = None) -> dict:
    """Entradas e resultado em JSON simples (texto para Decimal), para registro e hash."""
    envelopes = envelopes or {}
    return {
        'site_limit_kw': _text(decision.get('site_limit_kw')),
        'building_load_kw': _text(decision.get('building_load_kw')),
        'station_cap_kw': _text(decision.get('station_cap_kw')),
        'available_kw': _text(decision.get('available_kw')),
        'sessions': {
            str(key): {'request_kw': _text(item['request_kw']), 'target_kw': _text(item['target_kw']),
                       'limited_by': item['limited_by'], 'envelope_kw': _text(envelopes.get(key))}
            for key, item in sorted(decision['sessions'].items(), key=lambda pair: str(pair[0]))
        },
        'envelopes': {str(key): _text(value) for key, value in sorted(envelopes.items(), key=lambda p: str(p[0]))
                      if key not in decision['sessions']},
    }


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def trigger(previous: dict | None, current: dict) -> str:
    """O que mudou entre dois ``snapshot``: o gatilho registrado da decisão."""
    if not previous:
        return 'initial'
    for key, name in (('building_load_kw', 'building_load_changed'), ('site_limit_kw', 'site_limit_changed'),
                      ('station_cap_kw', 'station_cap_changed')):
        if previous.get(key) != current.get(key):
            return name
    before, after = set(previous.get('sessions', {})), set(current.get('sessions', {}))
    if after - before:
        return 'session_started'
    if before - after:
        return 'session_ended'
    if any(previous['sessions'][key]['request_kw'] != current['sessions'][key]['request_kw'] for key in after):
        return 'request_changed'
    return 'power_confirmed'
