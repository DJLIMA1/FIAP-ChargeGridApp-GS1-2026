"""Métodos do dashboard do proprietário comuns a ``ApiClient`` e ``DemoApi``.

Ambos os clientes herdam deste mixin; ele só depende de ``request`` e
``download``, então a mesma tela funciona com a API real e com a demonstração.
"""

OWNER_RESOURCES = ('overview', 'timeseries', 'heatmap', 'sessions', 'reservations', 'alerts', 'live')
EXPORT_DATASETS = ('sessions', 'reservations', 'margin')
EXPORT_FORMATS = ('csv', 'json', 'pdf')
# Formatos de cada exportação (o resultado/margem sai em CSV ou PDF, como no painel).
DATASET_FORMATS = {'sessions': ('csv', 'json'), 'reservations': ('csv', 'json'), 'margin': ('csv', 'pdf')}


def clean_params(params):
    """Remove filtros vazios para não enviar ``station_id=`` ou ``q=``."""
    return {key: value for key, value in (params or {}).items() if value not in (None, '', [], ())}


class OwnerApiMixin:
    async def owner_get(self, resource, params=None):
        if resource not in OWNER_RESOURCES:
            raise ValueError(f'Recurso desconhecido: {resource}')
        return await self.request('GET', f'owner/{resource}', params=clean_params(params))

    async def owner_overview(self, params=None):
        return await self.owner_get('overview', params)

    async def owner_timeseries(self, params=None):
        return await self.owner_get('timeseries', params)

    async def owner_heatmap(self, params=None):
        return await self.owner_get('heatmap', params)

    async def owner_sessions(self, params=None):
        return await self.owner_get('sessions', params)

    async def owner_reservations(self, params=None):
        return await self.owner_get('reservations', params)

    async def owner_alerts(self, params=None):
        return await self.owner_get('alerts', params)

    async def owner_live(self, params=None):
        return await self.owner_get('live', params)

    async def owner_export(self, dataset, fmt, params=None):
        """Bytes do arquivo exportado com os mesmos filtros da tabela.

        ``sessions``/``reservations``: CSV ou JSON; ``margin`` (resultado do período): CSV ou PDF."""
        if fmt not in DATASET_FORMATS.get(dataset, ()):
            raise ValueError('Exportação indisponível')
        return await self.download(f'owner/export/{dataset}.{fmt}', params=clean_params(params))

    async def owner_margin(self, params=None):
        """Resultado do período (``GET /v1/owner/margin``): receita, comissão, repasse, custo e margem."""
        return await self.request('GET', 'owner/margin', params=clean_params(params))

    async def station_economics(self, station_id):
        """Custo do kWh e comissão (só leitura) do posto (``GET /v1/stations/{id}/economics``)."""
        return await self.request('GET', f'stations/{station_id}/economics')

    async def update_station_economics(self, station_id, energy_cost_per_kwh):
        """Grava o custo do kWh (``None`` = não informado). A comissão nunca é enviada."""
        return await self.request('PUT', f'stations/{station_id}/economics',
                                  {'energy_cost_per_kwh': energy_cost_per_kwh})

    async def owner_insights(self, params=None):
        """Recomendações de IA (``POST /v1/ai/owner-insights``)."""
        return await self.request('POST', 'ai/owner-insights', clean_params(params))
