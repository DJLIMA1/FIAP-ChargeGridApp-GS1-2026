"""Estado de filtros do dashboard (puro, sem Flet) e rótulos em português."""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from chargegrid_core import analytics

SECTIONS = (
    ('overview', 'Visão geral'),
    ('stations', 'Postos e pontos'),
    ('sessions', 'Sessões e reservas'),
    ('coupons', 'Cupons'),
    ('insights', 'Insights IA'),
)
SESSION_STATUS_LABELS = {
    'starting': 'Iniciando', 'charging': 'Em recarga', 'stopping': 'Encerrando',
    'completed': 'Concluída', 'interrupted': 'Interrompida', 'failed': 'Falhou',
}
RESERVATION_STATUS_LABELS = {
    'pending_device': 'Aguardando ponto', 'confirmed': 'Confirmada', 'cancelling': 'Cancelando',
    'cancelled': 'Cancelada', 'expired': 'Expirada (não compareceu)', 'consumed': 'Utilizada',
}
SOURCE_LABELS = {'simulated': 'Simulada', 'measured': 'Medida', 'estimated': 'Estimada'}
END_REASON_LABELS = {
    'duration_limit': 'Limite de tempo', 'cost_limit': 'Limite de valor', 'requested': 'Pedido no app',
    'local_stop': 'Parada no painel', 'communication_lost': 'Comunicação perdida',
    'device_reboot': 'Reinício do painel', 'device_fault': 'Falha do equipamento', 'start_timeout': 'Início não confirmado',
}
IMPACT_LABELS = {'high': 'Alto impacto', 'medium': 'Médio impacto', 'low': 'Baixo impacto'}
KIND_LABELS = {'pricing': 'Tarifa', 'maintenance': 'Manutenção', 'operations': 'Operação',
               'marketing': 'Promoção', 'demand': 'Demanda', 'energy': 'Energia'}


@dataclass
class DashboardState:
    section: str = 'overview'
    period: str = '7d'
    custom_start: date | None = None
    custom_end: date | None = None
    station_id: str | None = None
    sidebar_collapsed: bool = False
    filters: dict = field(default_factory=dict)

    def bounds(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if self.period == 'custom':
            return analytics.period_bounds('custom', now, start=self.custom_start, end=self.custom_end)
        return analytics.period_bounds(self.period, now)

    def params(self, now: datetime | None = None, **extra):
        start, end = self.bounds(now)
        result = {'from': start.isoformat(), 'to': end.isoformat()}
        if self.station_id:
            result['station_id'] = self.station_id
        result.update({key: value for key, value in extra.items() if value not in (None, '')})
        return result

    def granularity(self, now: datetime | None = None):
        start, end = self.bounds(now)
        return analytics.suggested_granularity(start, end)

    def set_custom(self, start, end):
        """Valida antes de aplicar; mantém o período anterior se inválido."""
        analytics.period_bounds('custom', start=start, end=end)
        self.period, self.custom_start, self.custom_end = 'custom', start, end

    def period_label(self):
        if self.period == 'custom' and self.custom_start and self.custom_end:
            return f"{self.custom_start:%d/%m/%Y} – {self.custom_end:%d/%m/%Y}"
        return {'today': 'Hoje', '7d': 'Últimos 7 dias', '30d': 'Últimos 30 dias'}.get(self.period, 'Período')


def bucket_label(iso_value, granularity):
    moment = analytics.parse_time(iso_value)
    if moment is None:
        return ''
    moment = moment.astimezone(analytics.REPORT_TZ)
    return moment.strftime('%Hh') if granularity == 'hour' else moment.strftime('%d/%m')


def local_time(value, pattern='%d/%m/%Y %H:%M'):
    moment = analytics.parse_time(value)
    return moment.astimezone(analytics.REPORT_TZ).strftime(pattern) if moment else '—'
