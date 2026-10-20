# Concorrentes no GitHub — EV Challenge GoodWe × FIAP 2026

Levantamento de 20/10/2026. Complementa a [análise dos pitches](analise-pitches-goodwe-fiap-2026.md): lá, o que cada equipe **disse** na banca; aqui, o que o **código público** de cada uma realmente faz.

## Como foi feito

- Ponto de partida: as 12 equipes da banca gravada ([vídeo](https://www.youtube.com/watch?v=MFYoHv4j3KQ)) e as legendas automáticas do vídeo, que corrigiram nomes mal transcritos.
- Busca no GitHub por nome de projeto, turma (1CCA, 1CCPG, 1CCPH, 1CCPI, 1CCPK…), RM de 6 dígitos, nomes dos integrantes e termos do desafio (GoodWe, HCA G2, eletroposto, ChargeGrid). Cerca de 700 repositórios triados; os prováveis foram clonados e **lidos** (nenhum código de terceiros foi executado). URLs de deploy foram testadas só com requisições de leitura.
- Cada equipe recebeu duas notas subjetivas: **maturidade técnica** (o que o código sustenta) e **risco para a FFIVE** (chance de nos superar na avaliação, somando código e força do pitch).

Limites: só enxergamos repositórios **públicos**. Algumas equipes mostraram no pitch coisas que não estão no GitHub (versão privada, ferramenta no-code ou demonstração montada). Quase todos os concorrentes fortes são feitos por **um único autor**, com commits enormes e sinais de geração por agentes de código; isso não diminui o que o produto faz, mas pesa numa defesa técnica.

## Correções de identificação

| Na transcrição/análise anterior | Na verdade |
| --- | --- |
| Amps | **EMPS** (Energy Management and Payment Solution), equipe 6 de 1CCA |
| Asset Charge | **AsterCharge**, equipe 5 de 1CCA |
| Voodoo Recharge | **GoodWe Charge**, equipe 1 de 1CCPI |
| Smart Charge, turma desconhecida | Turma **1CCA** |
| Projeto sobre overstay | **ElectroBrain V2X** (Nexum Energy), equipe 4 de 1CCPH |

## Ranking de risco — equipes da nossa banca

| # | Equipe (turma) | Repositório principal | Maturidade | Risco | Por quê |
| --- | --- | --- | ---: | ---: | --- |
| 1 | **EMPS** (1CCA, eq. 6) | [TommasoNagliatti/EMPS-Ecosystem](https://github.com/TommasoNagliatti/EMPS-Ecosystem) | 8 | **8** | Otimização MILP real (48 passos de 15 min), previsão LightGBM com métricas fora do treino, Stripe teste com pré-autorização e captura, caixa sem app, API pública no ar (`api.emps-charge.tech`), ~300 testes e CI. Fraco: dados sintéticos, sem OCPP/Modbus, ESP32 nunca visto funcionando. |
| 2 | **Smart Charge** (1CCA) | [Vitormk1/challange](https://github.com/Vitormk1/challange) | 8 | **8** | Site no ar (`smartcharge.ia.br`), Asaas sandbox com Pix e webhook, carteira, algoritmo de demanda que respeita o limite e "leilão de potência" (menos kW por mais cashback), 3 modelos de fidelidade, LLM via OpenRouter, maquete Arduino gravando no banco de produção, 146 testes, CI com busca de segredos. Fraco: sem app nativo, previsão é regra e não ML. |
| 3 | **ChargeGrid** (1CCPG, eq. 5) | [Camper-Lingo/Chargegrid](https://github.com/Camper-Lingo/Chargegrid) | 4 | **7** | Melhor pitch da banca. O código público é raso: carga em `Math.random`, sem pagamento, sem testes, API em localhost; a gestão de demanda mostrada na demo **não está no repositório**. O risco vem da apresentação, não da base técnica. |
| 4 | **ChargeGrid Intelligence** (1CCPI, eq. 3) | [mathsant-js/ChargeGrid-Intelligence](https://github.com/mathsant-js/ChargeGrid-Intelligence) | 7 | **5–6** | FastAPI + Postgres + Alembic, CI com ruff/mypy/pytest verde, ~160 testes, alocação de potência que respeita a rede, RandomForest comparado a baseline. Fraco: front pequeno, sem app, sem hardware, sem deploy, tarifa fixa. |
| 5 | **ChargeOps Assistant** (1CCPK, eq. 5) | [DaviZuolo07/GoodWe_MVP](https://github.com/DaviZuolo07/GoodWe_MVP) | 7,5 | **5** | Medição **física real** (5 sensores INA219), RFID, alocador alinhado aos registradores Modbus do HCA G2, Supabase com RLS, auth forte, LLM com avaliação RAGAS, ~240 testes. Fraco: é da trilha condomínio, sem deploy, pitch estourou o tempo. Sobe para 6–7 se o totem funcionar bem na final. |
| 6 | AsterCharge (1CCA, eq. 5) | [laraarinhaa226/Sprint4_SERS](https://github.com/laraarinhaa226/Sprint4_SERS) | 3 | 4 | App e painel do pitch não são públicos; só firmware pequeno e chatbot em notebook. Risco vem só da narrativa de tarifa solar + demanda. |
| 7 | ElectroBrain / overstay (1CCPH, eq. 4) | [eduardonovaki/sprint](https://github.com/eduardonovaki/sprint) | 2 | 4 | Feito no Base44 (no-code), sem código-fonte. Stripe e a dor de overstay agradam; qualquer olhar técnico derruba. Chave de API commitada num `.env`. |
| 8 | Smart HMI (1CCPI, eq. 2) | [doern-felipe/GoodWeChallenge-SmartHMI](https://github.com/doern-felipe/GoodWeChallenge-SmartHMI) | 3 | 4 | Visual de HMI muito polido; RFID, chat e tarifa são simulados; sem backend. |
| 9 | WeCharge (1CCA, eq. 7) | [GabrielSavoy/WeCharge](https://github.com/GabrielSavoy/WeCharge) | 3,5 | 3 | Um único HTML; maquete Arduino real via Web Serial; a "análise de IA" do painel é animação. |
| 10 | GoodWe Charge (1CCPI, eq. 1) | [PHCDS/goodwe-charge-sprint3](https://github.com/PHCDS/goodwe-charge-sprint3) | 3 | 3 | ESP32 → MQTT público → site no ar; firmware do repo não compila; login e pagamento falsos. |
| 11 | ChargeGrid Intelligence Hub (1CCPK, eq. 3) | [wendelprezende/Sprint3_PCP_SERS](https://github.com/wendelprezende/Sprint3_PCP_SERS) | 3,5 | 2 | Balanceamento com histerese bem feito, mas Flask + SQLite local, sem login, testes ou deploy. |

**Leitura:** dois concorrentes são fortes **no código e no pitch** ao mesmo tempo — EMPS e Smart Charge, ambos da 1CCA. Os dois cobrem justamente as lacunas que a banca apontou em nós (pagamento e demanda). O ChargeGrid da 1CCPG é perigoso só pela apresentação.

## Fora da banca — risco no ranking global

Estas equipes não apareceram na gravação (outras turmas ou outra banca), mas pesam se a classificação for geral.

| Equipe (turma) | Repositório | Maturidade | Destaque |
| --- | --- | ---: | --- |
| **STIG4 Solutions** (1CCR) | [STIG4-Solutions/chargegrid-challenge](https://github.com/STIG4-Solutions/chargegrid-challenge) | **9,5** | O mais maduro de todos: API em produção (`api.stig4.com`) com staging separado, ~1.190 testes, CI completo, balanceamento por prioridade com garantia de limite, tarifa por "bandeira" de folga de potência, LightGBM, Pix BACEN escrito (não homologado), assistente com 24 ferramentas, APK publicado. Sem hardware. |
| ChargeGrid-Manager / GTLF (1CCR) | [rafaperes21/ChargeGrid-Manager](https://github.com/rafaperes21/ChargeGrid-Manager) | 7,5 | Demanda com solar + bateria, Prophet real, estudo A×B quantificado, 287 testes. Sem deploy, sem pagamento. |
| charge-grid-hub (1CCPY) | [ArthurPB25/charge-grid-hub](https://github.com/ArthurPB25/charge-grid-hub) | 7,5 | Pix Mercado Pago sandbox, ESP32 com relé via MQTT, alocação por prioridade. Persistência em JSON. |
| 1CCR equipe 04 | [gabriela-angel/chargegrid_challenge](https://github.com/gabriela-angel/chargegrid_challenge) | 7 | Redistribuição com orçamento solar, Pix Mercado Pago sandbox, Modbus pymodbus. Tokens de pagamento commitados num repo irmão. |
| Sistema-charge-gridd (1CCPF) | [pedrosampaiom2007-gif/Sistema-charge-gridd](https://github.com/pedrosampaiom2007-gif/Sistema-charge-gridd) | 7 | Flask + Postgres, RandomForest, Mercado Pago sandbox, RAG. Balanceamento por divisão igual. |
| ChargeGrid (1CCPX) | [herbertsoaress/chargegrid](https://github.com/herbertsoaress/chargegrid) | 7 | OCPP 1.6J e Modbus reais (com equipamentos virtuais), tarifa por ocupação prevista, 260 testes. |
| GoodWe Power Charge (1CCPQ provável) | [vencedoresdonext](https://github.com/vencedoresdonext) | 7 | NestJS + Prisma + Redis, Mercado Pago real com webhook HMAC. Sem gestão de demanda; deploys fora do ar. |
| ChargeGrid Intelligence (1CCPQ, eq. 7) | [PtiagoM/Charge-Grid-Intelligence](https://github.com/PtiagoM/Charge-Grid-Intelligence) | 6,5 | Stripe teste funcionando (autorizar, capturar, estornar, Pix), PWA. Dono do domínio `chargegrid-api.vercel.app` — **nunca citar esse domínio curto no nosso pitch**; o nosso é o alias `chargegrid-api-preview-djlima1s-projects.vercel.app`. |
| Ponto W (1CCPO) | [jbelkior1/gs_goodwe](https://github.com/jbelkior1/gs_goodwe) | 5,5 | Demanda e tarifa algorítmicas, tese de franquia, VR. Sem backend no ar (branch `mvp` em andamento). |

Fracos ou de outra trilha (resumo): FlowK/Khaos Flow ([ymCarvalho/ChargeGrid](https://github.com/ymCarvalho/ChargeGrid), API mock e app sem chamar a API), AXIS, Henrique-E-Silveira, giovanesalazar, LuRSousa, NexusCharge (1CCPZ, 270 testes mas Flask simples), Chargegrid-Team04, EcovoltSquad, ChargeFlow (1CCPX, deploy no ar mas sem pagamento), FIAP-workd (trilha condomínio).

## Onde a FFIVE fica nesse quadro

**Onde ninguém nos alcança:**
- **Hardware próprio com confirmação de comando.** Painel ESP32-S3 com LVGL e ACK do dispositivo. Os outros têm maquete Arduino via USB/Web Serial, ESP32 em branch nunca testada ou nada. Só o ChargeOps Assistant tem medição física mais real que a nossa.
- **Produto inteiro publicado e integrado.** App Android distribuído com atualização automática, painel web na Vercel e API real. Entre os concorrentes, só STIG4, Smart Charge e EMPS também têm algo comparável no ar.
- **Propriedade do equipamento por QR privado + código público de recarga** e reservas com planejamento por orçamento/tempo: não encontrei equivalente em nenhum repositório.
- **Preço dinâmico por demanda já calculado pelo sistema** (ocupação, tendência, fila e pico do dono, com o preço travado para o motorista). Poucos têm algo além de tarifa fixa ou por horário.

**Onde estamos atrás dos líderes:**
1. **Pagamento.** É a maior diferença. EMPS (Stripe), Smart Charge (Asaas), PtiagoM (Stripe), vencedoresdonext e três equipes com Mercado Pago já têm **sandbox integrado**. Nós somos dos poucos fortes sem nenhum. Um Pix/cartão em sandbox (Mercado Pago, Asaas ou Stripe), com webhook confirmando, fecha essa lacuna.
2. **Rebalanceamento ao vivo.** Já dividimos o teto do posto entre os conectores (`packages/chargegrid_core/chargegrid_core/power.py`: divisão proporcional, piso de 1,4 kW, soma ≤ teto). Mas a divisão vale **só para o próximo início de recarga** e não olha o consumo da loja nem o solar. Smart Charge, EMPS, STIG4 e ChargeGrid Intelligence redistribuem durante a sessão. Falta reaplicar a divisão a cada mudança (sessão nova, fim de sessão, consumo do estabelecimento) e mostrar isso no painel ESP32.
3. **Previsão com métrica.** EMPS, STIG4 e ChargeGrid Intelligence mostram modelo treinado com erro medido contra um baseline. Responder "qual a metodologia?" com um número é algo que a banca já perguntou.

## Recomendação

1. **Pagamento em sandbox antes de qualquer outra feature.** Não exige mudar a arquitetura e anula o principal argumento do EMPS e do Smart Charge contra nós.
2. **Rebalanceamento contínuo usando a mesma regra de `power.py`**, acionado por eventos, com o painel físico mostrando a potência mudando quando outro carro entra. É a demo de causa e efeito que fez a 1CCPG ganhar a banca, só que com hardware de verdade.
3. **No pitch, atacar o que só nós temos:** dispositivo físico confirmando cada comando, app instalado no celular e QR de propriedade. EMPS e Smart Charge trabalham com dados sintéticos e maquetes simples; nossa recarga acontece num painel real.
4. **Não exagerar.** Os concorrentes fortes documentam com honestidade o que é real e o que é simulado. Se a banca perceber exagero na nossa demonstração, perdemos a vantagem de credibilidade.
