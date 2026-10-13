"""Métodos do dashboard do proprietário comuns a ``ApiClient`` e ``DemoApi``.

Ambos os clientes herdam deste mixin; ele só depende de ``request`` e
``download``, então a mesma tela funciona com a API real e com a demonstração.
"""

OWNER_RESOURCES = ('overview', 'timeseries', 'heatmap', 'sessions', 'reservations', 'alerts', 'live')
EXPORT_DATASETS = ('sessions', 'reservations')
EXPORT_FORMATS = ('csv', 'json')


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
        """Bytes do arquivo exportado (CSV ou JSON) com os mesmos filtros da tabela."""
        if dataset not in EXPORT_DATASETS or fmt not in EXPORT_FORMATS:
            raise ValueError('Exportação indisponível')
        return await self.download(f'owner/export/{dataset}.{fmt}', params=clean_params(params))

    async def owner_insights(self, params=None):
        """Recomendações de IA (``POST /v1/ai/owner-insights``)."""
        return await self.request('POST', 'ai/owner-insights', clean_params(params))
