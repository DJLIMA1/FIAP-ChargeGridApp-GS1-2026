"""Resultado do dono do posto: configuração (custo do kWh, comissão) e a margem por sessão.

Uma única agregação (``chargegrid_core.economics``) alimenta a tela, o CSV e o PDF. As
sessões elegíveis seguem a regra do overview do painel (``owner.service._eligible``):
encerradas com energia positiva e término dentro do período.
"""


from sqlalchemy import or_, select

from chargegrid_core import analytics, economics
from chargegrid_core import rent as rent_rules

from ...errors import fail
from ...models import CentralRentRate, ChargingSession, Connector, Device, DeviceClaim, Station, now
from ..owner.service import EXPORT_LIMIT, _eligible, _owned_sessions
from ..payments.funding import channel_by_session, payments_by_session
from ..receipts.registry import extras_for

FEE_READ_ONLY = "A comissão da plataforma é definida em contrato e não pode ser alterada no painel."
RENT_READ_ONLY = ("Aluguel mensal por central: definido em contrato, rateado pelos dias de vínculo no mês e "
                  "descontado do repasse.")


# ------------------------------------------------------------ configuração

def snapshot_session(db, session, connector, terms, coupon=None):
    """Grava na sessão recém-criada a explicação do preço (com o cupom), o custo do kWh e a
    comissão vigentes no posto. Mudanças posteriores não reescrevem esta recarga."""
    station = db.get(Station, connector.station_id)
    terms = dict(terms or {})
    if coupon is not None:
        terms["coupon"] = {"id": str(coupon.id), "code": coupon.code, "discount_percent": int(coupon.discount_percent)}
    session.price_terms = terms
    session.energy_cost_per_kwh = station.energy_cost_per_kwh
    session.platform_fee_percent = station.platform_fee_percent


def station_economics(station, notes=True, db=None, rates=None, centrals=None) -> dict:
    """Configuração do posto. Com ``db`` (ou ``rates``/``centrals`` já carregados), também o
    aluguel mensal por central vigente hoje (``None`` = sem aluguel) e as centrais vinculadas."""
    cost = station.energy_cost_per_kwh
    result = {
        "station_id": str(station.id),
        "energy_cost_per_kwh": analytics.decimal_text(cost, "0.0001") if cost is not None else None,
        "platform_fee_percent": analytics.decimal_text(station.platform_fee_percent, "0.01"),
        "fee_editable": False,
        "currency": "BRL",
    }
    if db is not None or rates is not None:
        rates = rent_rates(db, [station.id]) if rates is None else rates
        monthly = rent_rules.current_rate(rates, station.id, now())
        if centrals is None:
            centrals = linked_centrals_count(db, [station.id]).get(station.id, 0)
        result.update(central_monthly_rent=analytics.decimal_text(monthly) if monthly is not None else None,
                      centrals=centrals, rent_editable=False)
    if notes:
        result["notes"] = [
            "Custo do kWh: informe o valor médio pago à distribuidora (R$/kWh). Vale para as próximas "
            "recargas; as anteriores mantêm o custo travado no início.",
            FEE_READ_ONLY,
        ]
        if result.get("central_monthly_rent") is not None:
            result["notes"].append(RENT_READ_ONLY)
    return result


# --------------------------------------------------------- aluguel das centrais

def rent_rates(db, station_ids) -> list[dict]:
    """Linhas de ``central_rent_rates`` do padrão e dos postos informados."""
    rows = db.scalars(select(CentralRentRate).where(or_(
        CentralRentRate.station_id.is_(None), CentralRentRate.station_id.in_(list(station_ids) or [None])))).all()
    return [{"station_id": row.station_id, "monthly_amount": row.monthly_amount,
             "effective_from": row.effective_from} for row in rows]


def _central_query(*columns):
    """Centrais = telas (dispositivo sem tela-mãe) de pontos vinculados por QR a um dono.
    Revogadas antes do registro de ``revoked_at`` ficam de fora (nunca cobradas)."""
    return (
        select(*columns)
        .select_from(Device)
        .join(Connector, Connector.id == Device.connector_id)
        .join(Station, Station.id == Connector.station_id)
        .join(DeviceClaim, DeviceClaim.connector_id == Connector.id)
        .where(Device.parent_device_id.is_(None), DeviceClaim.claimed_at.is_not(None), Station.owner_id.is_not(None),
               or_(Device.revoked.is_(False), Device.revoked_at.is_not(None)))
    )


def linked_centrals_count(db, station_ids) -> dict:
    rows = db.execute(_central_query(Station.id).where(Station.id.in_(list(station_ids) or [None]),
                                                       Device.revoked.is_(False))).scalars().all()
    counts: dict = {}
    for station_id in rows:
        counts[station_id] = counts.get(station_id, 0) + 1
    return counts


def central_rent(db, scope, window, moment=None) -> dict:
    """``chargegrid_core.rent.accrual`` das centrais do dono (ou do posto) na janela."""
    moment = moment or now()
    station_ids = db.scalars(scope.stations(select(Station.id))).all()
    rates = rent_rates(db, station_ids)
    if not rates or not station_ids:
        return rent_rules.accrual([], [], window.start, window.end, moment)
    records = db.execute(scope.stations(_central_query(
        Device.id, Device.created_at, Device.revoked_at, DeviceClaim.claimed_at,
        Station.id.label("station_id"), Station.name.label("station_name"), Connector.public_code,
    ).where(DeviceClaim.claimed_at < window.end,
            or_(Device.revoked_at.is_(None), Device.revoked_at > window.start),
            or_(Device.created_at.is_(None), Device.created_at < window.end)))).mappings().all()
    centrals = [{
        "device_id": record["id"], "station_id": record["station_id"], "station_name": record["station_name"],
        "central": record["public_code"],
        "linked_at": max(filter(None, (record["claimed_at"], record["created_at"]))),
        "unlinked_at": record["revoked_at"],
    } for record in records]
    return rent_rules.accrual(centrals, rates, window.start, window.end, moment)


def update_station_economics(station, body) -> None:
    if not isinstance(body, dict):
        fail("invalid_economics", "Envie um objeto com energy_cost_per_kwh.", 422)
    if "platform_fee_percent" in body:
        fail("fee_read_only", FEE_READ_ONLY, 422)
    unknown = sorted(set(body) - {"energy_cost_per_kwh"})
    if unknown:
        fail("invalid_economics", "Campo não permitido: " + ", ".join(unknown), 422)
    if "energy_cost_per_kwh" in body:
        try:
            station.energy_cost_per_kwh = economics.clean_energy_cost(body["energy_cost_per_kwh"])
        except ValueError as error:
            fail("invalid_economics", str(error), 422)


# ------------------------------------------------------------------ margem

MARGIN_COLUMNS = (
    ChargingSession.id, ChargingSession.ended_at, ChargingSession.source, ChargingSession.energy_wh,
    ChargingSession.price_per_kwh, ChargingSession.base_price_per_kwh, ChargingSession.demand_multiplier,
    ChargingSession.discount_percent, ChargingSession.cost_estimate, ChargingSession.price_terms,
    ChargingSession.energy_cost_per_kwh, ChargingSession.platform_fee_percent,
    Station.id.label("station_id"), Station.name.label("station_name"), Connector.public_code,
    Station.energy_cost_per_kwh.label("station_energy_cost"),
    Station.platform_fee_percent.label("station_fee_percent"),
)


def margin_rows(db, scope, window) -> list[dict]:
    """Linhas ``economics.session_economics`` de todas as sessões elegíveis (ordem estável)."""
    records = db.execute(
        _owned_sessions(scope, *MARGIN_COLUMNS)
        .where(_eligible(window))
        .order_by(ChargingSession.ended_at.desc(), ChargingSession.id.desc())
        .limit(EXPORT_LIMIT + 1)
    ).mappings().all()
    if len(records) > EXPORT_LIMIT:
        fail("export_too_large", f"Mais de {EXPORT_LIMIT} sessões. Reduza o período ou filtre um posto.", 413)
    # Os provedores do registro recebem as sessões de verdade: a permanência (frente D) lê as
    # colunas ``overstay_*`` da própria sessão (um id solto derrubava a seção e zerava a taxa).
    ids = [record["id"] for record in records]
    sessions = db.scalars(select(ChargingSession).where(ChargingSession.id.in_(ids))).all() if ids else []
    extras = extras_for(db, sessions)
    # Totem 0.8.0: canal e método de cada recarga (colunas no fim do CSV e do PDF).
    channels = channel_by_session(db, payments_by_session(db, ids))
    return [
        economics.session_economics(dict(record), station_energy_cost=record["station_energy_cost"],
                                    station_fee_percent=record["station_fee_percent"],
                                    extras=extras.get(record["id"]))
        | analytics.payment_export_fields(channels.get(record["id"]))
        for record in records
    ]


def stations_config(db, scope) -> list[dict]:
    stations = db.scalars(scope.current(select(Station)).order_by(Station.name, Station.id)).all()
    ids = [station.id for station in stations]
    rates = rent_rates(db, ids) if ids else []
    counts = linked_centrals_count(db, ids) if ids else {}
    return [{**station_economics(station, notes=False, rates=rates, centrals=counts.get(station.id, 0)),
             "station_name": station.name} for station in stations]


def margin_report(db, scope, window, rows=None) -> dict:
    """Relatório completo (``Decimal``): totais, efeitos, quebra por posto, linhas e método."""
    rows = margin_rows(db, scope, window) if rows is None else rows
    report = economics.aggregate(rows, rent=central_rent(db, scope, window))
    report.update(
        schema_version=economics.SCHEMA_VERSION,
        period={"from": window.start.isoformat(), "to": window.end.isoformat(),
                "timezone": analytics.REPORT_TZ_NAME},
        basis="ended_at",
        currency="BRL",
        station_id=str(scope.station_id) if scope.station_id else None,
        stations=stations_config(db, scope),
        methodology=list(economics.METHODOLOGY),
        generated_at=now().isoformat(),
        items=rows,
        total=len(rows),
    )
    return report
