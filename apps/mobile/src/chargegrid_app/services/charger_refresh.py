"""Station reads for the charger pages: one request, route lifetime and mutation ordering."""

from .. import api_cache

POLL_SECONDS = 2
TELEMETRY_FIELDS = ('online', 'available', 'availability_status', 'physical_state', 'retired',
                    'charger_link', 'screen', 'screen_online', 'unavailable_reason', 'kiosk_in_use',
                    'reserved_until', 'effective_power_kw', 'power_limited', 'power_limited_by')


class StationRefresh:
    def __init__(self, app, station_id):
        self.app, self.station_id = app, station_id
        self.generation = getattr(app, 'generation', None)
        self.revision = 0
        self.running = False

    def invalidate(self):
        self.revision += 1

    async def read(self):
        if (self.running or getattr(self.app, 'closed', False) or getattr(self.app, 'backgrounded', False)
                or getattr(self.app, 'prompting', False)
                or getattr(self.app, 'generation', None) != self.generation):
            return None
        self.running = True
        revision = self.revision
        try:
            with api_cache.network_only():
                station = await self.app.api.request('GET', f'stations/{self.station_id}')
            if (revision != self.revision or getattr(self.app, 'closed', False)
                    or getattr(self.app, 'backgrounded', False)
                    or getattr(self.app, 'prompting', False)
                    or getattr(self.app, 'generation', None) != self.generation
                    or getattr(self.app, 'active_actions', None)):
                return None
            return station
        finally:
            self.running = False


def merge_telemetry(connector, fresh):
    """Editable values belong to the form; telemetry can change without replacing its controls."""
    for key in TELEMETRY_FIELDS:
        if key in fresh:
            connector[key] = fresh[key]
