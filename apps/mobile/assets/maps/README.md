# Mapa local da demonstração

`demo-centro.svg` é um recorte vetorial geográfico da Praça da Sé, São Paulo, para a localização pública e fictícia da conta demo. Não é uma captura de tiles: foi gerado a partir de 291 feições OSM consultadas uma vez via Overpass. O marcador representa as coordenadas do posto de exemplo, não a localização do usuário. A demo carrega a versão rasterizada `demo-centro.png` localmente, sem HTTP, GPS ou persistência de dados da conta. O PNG mantém os nomes das vias legíveis no renderizador do app; o SVG permanece como fonte geográfica.

Dados: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL. Estilo e montagem: ChargeGrid. O crédito `© OpenStreetMap` permanece visível, de forma compacta, no canto inferior direito e leva à página de origem/licença. A faixa inteira foi removida, não a atribuição exigida pelas [diretrizes](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) e pela política do servidor de tiles. Para outra coordenada demo, busca com referência explícita ou ponto indisponível, o aplicativo usa a visão esquemática identificada, sem reaproveitar um marcador fixo de ponto disponível.

O gerador reproduzível fica em `tools/generate_demo_map.py`; executar exige rede e faz uma consulta limitada à área mostrada. Não é executado pelo aplicativo. Nas contas reais, o mapa online mantém crédito visível e cache dos tiles consultados conforme a [política do serviço OSM](https://operations.osmfoundation.org/policies/tiles/).

Para rasterizar novamente a fonte existente, sem rede:

```sh
PYTHONPATH=apps/mobile/src .venv/bin/python tools/render_demo_map.py
```

O enquadramento tem proporção 563:389, marcador em 40% da largura e cartão branco lateral. Início e lista de postos usam esse mesmo componente; o mapa genérico compartilha a moldura e a atribuição. O app adapta essa composição à largura disponível, sem refazer downloads ao redimensionar. O botão de recarga mantém as dimensões padrão do aplicativo, independentemente da largura do mapa.
