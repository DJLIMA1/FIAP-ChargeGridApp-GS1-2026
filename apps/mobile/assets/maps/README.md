# Mapas vetoriais compartilhados

Todos os mapas exibidos pelo aplicativo usam OpenFreeMap + MapLibre: recarga, detalhes dos postos, mapa genérico e galeria visual. A conta demo usa o mesmo mapa real nas coordenadas dos postos fictícios. Nenhuma tela usa o raster de referência para representar outra localização.

O ponto de entrada é `chargegrid_app/ui/vector_map.py`. Os estilos `styles/liberty.json` e `styles/dark.json` vieram de https://tiles.openfreemap.org/styles/liberty e https://tiles.openfreemap.org/styles/dark. O app aplica suas cores diretamente às camadas vetoriais. Ruas e textos são desenhados pelo MapLibre, com suavização e densidade mínima de 2× na versão web, mesmo em prévias com DPR=1. Essa configuração fica em `map-runtime.js` e mantém o tamanho lógico dos textos e o zoom geográfico. Os dois créditos obrigatórios aparecem por cinco segundos após carregar o mapa e se recolhem ao mover o mapa ou ao fechar o controle. O botão ⓘ permanece visível e reabre os links de atribuição e licença. Isso segue https://osmfoundation.org/wiki/Licence/Attribution_Guidelines#Interactive_maps. A marca opcional OpenFreeMap não ocupa espaço na tela.

Os tiles vêm de https://tiles.openfreemap.org/planet. O serviço público não exige chave. Dados © OpenStreetMap contributors; esquema © OpenMapTiles; hospedagem OpenFreeMap. Os links de atribuição ficam sobre o mapa, acima do painel da lista. A conexão pode falhar: o componente oferece tentar novamente e não inventa geografia offline. O GPS só é solicitado pelo fluxo explícito já existente no app.

A extensão local `packages/chargegrid_map` contém o renderizador Flutter compartilhado, seus eventos de câmera e seleção, e a proteção de toques nos controles flutuantes sobre a versão web. O painel e os marcadores são atualizados sem remontar o mapa durante o polling.

Para desenvolver a prévia web, a partir da raiz:

```sh
.venv/bin/python -m pip install -e apps/mobile/packages/chargegrid_map
.venv/bin/python tools/build_mobile_web_client.py
PYTHONPATH=apps/mobile/src .venv/bin/python tools/preview_mobile_flows.py
```

`FLET_WEB_PATH` aponta para `apps/mobile/.flet/vector-client/build/web`. O cliente padrão do Flet não contém extensões locais. Nos builds Android/iOS, `apps/mobile/pyproject.toml` registra a extensão automaticamente. Requer Flutter 3.44 ou superior.

O runtime web MapLibre GL JS 5.16.0 e seu CSS são distribuídos localmente, com a licença em `MAPLIBRE-LICENSE.txt`. Os arquivos antigos `demo-centro.*` e `assets/design/map_villa_lobos*.jpg` são fontes históricas de design, sem uso nas telas atuais.
