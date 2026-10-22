# Revisão da análise para apresentação — 21/10/2026

Base: `main` **fc510e8 + alterações locais**, comparada à primeira análise de **5f88d2a**, em 20/10. Foram consideradas também as mudanças não commitadas em mapas, tarifação, empacotamento e impressão. Não alterei código do produto nem testes; os dois documentos de apresentação são as entregas desta tarefa.

**Os 156 itens originais foram classificados um a um: 122 confirmados, 10 ajustados e 24 com ressalva.** “Confirmado” significa aderência à implementação/testes locais, não certificação física nem comprovação do deploy. Além deles, o [guia atualizado](apresentacao-faculdade-10-minutos.md) ganhou **30 detalhes novos (L1–L30)**.

## Mudanças que afetam a fala principal

| Afirmação anterior ou interpretação possível | Resultado da revisão |
|---|---|
| Transporte real do HCA desabilitado em todo o projeto | **Desatualizada.** A classe Python antiga continua bloqueada; o painel agora tem cliente TCP C++ e há servidor no novo firmware emulador. Cinco testes por socket local passaram. |
| O mesmo firmware já suporta os três modelos HCA | **Exagerada.** Python contempla 7/11/22 kW; mapa/firmware C++ atual usam GW7K de 7 kW. |
| Só havia consumo de loja informado manualmente | **Incompleta.** Agora são seis perfis, três portes e curva automática reproduzível; override manual expira em 30 min. |
| Painel web mostra LivePanel na visão geral | **Desatualizada.** Esse componente foi removido; potência fica em PowerCard dentro da estação, com atualização de 3 s quando visível. |
| Qualquer sobreposição de tarifa é rejeitada | **Precisa de escopo.** Só horários ativos conflitam; enabled=false conserva a configuração sem aplicá-la. |
| Os mapas atuais têm fallback esquemático e demo sem tiles externos | **Desatualizada.** MapLibre/OpenFreeMap desenha geografia vetorial; indisponibilidade mostra nova tentativa e tiles dependem de rede. |
| A única comunicação relevante expira em 45 s | **Incompleta.** Há 45 s sem API, 5 s de perda do carregador na sessão Modbus e 15 s sem mestre no firmware emulador. |
| Mudança do setpoint altera a potência real do celular | **Incorreta para essa bancada.** O relé é binário e potência/energia são simuladas a partir do setpoint; não há medidor nem regulação variável USB comprovada. |
| A peça 5 deve seguir apenas o pacote v9 | **Incompleta.** Há revisão R10 de orientação/fatiamento em 21/10, específica dessa peça e sem nova geometria de produção. |
| Todos os testes continuam verdes | **Incorreta hoje.** Os grupos executados têm 1.607 aprovados e duas falhas do app documentadas. |

## Frase GoodWe atualizada

> “Implementamos um cliente Modbus TCP no painel e um firmware separado que emula o HCA G2 de 7 kW. Os testes locais exercitam o protocolo e a confirmação por releitura. Potência e energia ainda são simuladas, e a validação num equipamento GoodWe comercial continua pendente.”

O endereço 1–247 é escolha configurável da bancada. O padrão 247 citado nas referências comunitárias do HCA real não deve ser confundido com o endereço automático 1, 2, 3… do emulador. Os registradores 19000–19006 são extensão de teste, não parte confirmada do mapa do fabricante. Mantém-se a distinção entre datasheet oficial e transcrições públicas do mapa detalhado.

## Verificações executadas

| Grupo | Resultado |
|---|---|
| Core | 246 aprovados |
| API em PostgreSQL 16 descartável | 425 aprovados; migrações até head aprovadas |
| React | 120 aprovados; TypeScript aprovado |
| App | 762 aprovados, **2 falhas**, 129 subtestes aprovados |
| Ferramentas selecionadas | 47 aprovados |
| Modbus TCP real em loopback contra emulador | 5 aprovados |
| Flutter do mapa: atribuição/créditos | 2 aprovados |
| Total, sem duplicar subtestes | **1.607 aprovados, 2 falhas** |
| Controlador/fluxo/UI LVGL compilados para host | Aprovados, inclusive link HCA, watchdog, falhas e QRs decodificados |

O banco foi criado exclusivamente para esta revisão em `/tmp`, acessível por loopback, e encerrado ao fim. O sandbox bloqueou inicialmente memória compartilhada e sockets; as execuções locais foram autorizadas e repetidas com sucesso. Nenhum banco existente ou hardware foi usado. O Flutter precisou escrever seu cache local para executar os testes já instalados.

### Duas falhas do app

- `test_demo_summary_reports_live_demo_result_and_demo_guidance`: esperava 1,000 kWh, mas a sessão demonstrativa retornou aproximadamente 0,947 kWh após limitação.
- `test_simulated_soc_rises_with_energy_and_stops_battery_full`: esperava 95%, mas retornou 94,73%.

Reprodução: ponto nominal **60 kW**, limite aplicado **56,8 kW**, loja **18,2 kW** num limite de **75 kW**; no intervalo calculado pelo teste usando 60 kW, a energia foi **473,333 Wh**. Com SoC inicial de 90% e capacidade modelada de 10 kWh, o resultado calculado é **94,73333%**, consistente com os 94,73% exibidos.

Essas falhas indicam expectativas baseadas em potência nominal anteriores ao novo balanceamento automático. A suíte mistura relógio de duração injetado com data/hora para a curva predial, portanto esses valores podem variar. Cabe isolar o cenário/relógio ou calcular expectativas pela potência aplicada; **não foi feita essa alteração nesta tarefa**. A primeira falha ocorre antes de outras verificações do teste; não se pode tomar o restante desse teste como aprovado.

## Conferência individual dos 156 itens originais

O título da primeira coluna é o da análise anterior; a última coluna registra a interpretação válida hoje. Cada linha aponta uma fonte concreta. As ressalvas evitam transformar código, teste com fronteira simulada ou relatório mecânico em prova de operação física.

| ID / ponto original | Situação | Evidência e conclusão |
|---|---|---|
| **A1** — Filtros por conector, disponibilidade e preço | Confirmado | [stations.py](../apps/mobile/src/chargegrid_app/screens/stations.py): Filtros continuam no painel de comparação; o mapa atual não os elimina. |
| **A2** — Conector normalizado: Tipo 2/type2 e CCS/ccs2 | Confirmado | [discovery.py](../apps/api/app/modules/stations/discovery.py): normalize_connector preserva equivalências de escrita para Tipo 2/CCS. |
| **A3** — Preço e características do cartão se referem ao mesmo ponto elegível | Confirmado | [discovery.py](../apps/api/app/modules/stations/discovery.py): discover escolhe o ponto elegível e mantém seus atributos no metadado de descoberta. |
| **A4** — Distância é calculada a partir da referência da busca | Confirmado | [discovery.py](../apps/api/app/modules/stations/discovery.py): Distância deriva de coordenadas da busca; não é rota nem tempo de deslocamento. |
| **A5** — Intenção de tempo ou orçamento acompanha a escolha | Confirmado | [stations.py](../apps/mobile/src/chargegrid_app/screens/stations.py): planning_intent e presets acompanham a navegação e os filtros. |
| **A6** — Fluxo também contém planejamento por autonomia estimada | Com ressalva | [booking.py](../apps/mobile/src/chargegrid_app/services/booking.py): Autonomia é conversão estimada, apoiada no consumo e SoC modelados; não é leitura do veículo. |
| **A7** — Autonomia estimada é limitada ao espaço livre da bateria modelada | Com ressalva | [booking.py](../apps/mobile/src/chargegrid_app/services/booking.py): autonomy_energy limita ao espaço calculado da bateria modelada; não prova capacidade física disponível. |
| **A8** — Limites de duração e custo são revisados antes do início | Confirmado | [charging.py](../apps/mobile/src/chargegrid_app/screens/charging.py): Wizard mantém revisão de limites antes de Solicitar início. |
| **A9** — Nova tarifa, potência ou condição exige nova revisão | Confirmado | [test_journey_trust.py](../apps/mobile/tests/test_journey_trust.py): Teste de nova revisão por mudança de preço passou na suíte do app. |
| **A10** — Voltar preserva filtros, local e rascunho quando válido | Confirmado | [navigation.py](../apps/mobile/src/chargegrid_app/navigation.py): Retorno mantém contexto da busca e etapas válidas; testes de navegação passaram. |
| **A11** — Estado de reserva/sessão muda a ação principal | Confirmado | [home.py](../apps/mobile/src/chargegrid_app/screens/home.py): Reserva/sessão existente continuam orientando a ação contextual da home. |
| **A12** — Perda de resposta mantém a identidade do pedido original | Confirmado | [api_client.py](../apps/mobile/src/chargegrid_app/api_client.py): Chaves da operação e recuperação da sessão preservam a identidade após resposta perdida. |
| **B1** — Código público `CG-` curto exclui 0/O e 1/I | Confirmado | [service.py](../apps/api/app/service.py): PUBLIC_CODE_ALPHABET continua sem 0/O e 1/I; formato público é CG- mais quatro caracteres. |
| **B2** — Código temporário `#F` muda a cada cinco minutos | Com ressalva | [presence_code.py](../apps/api/app/presence_code.py): Código HMAC muda em janelas de 300 s; pode ser compartilhado por alguém, logo não certifica presença física. |
| **B3** — Código temporário usa segredo do posto e HMAC | Confirmado | [presence_code.py](../apps/api/app/presence_code.py): Segredo do posto, ID e janela entram no HMAC; comparação usa compare_digest. |
| **B4** — Segredo de propriedade é diferente do código público | Confirmado | [routes.py](../apps/api/app/modules/ownership/routes.py): Claim usa token próprio e não aceita código público como prova de propriedade. |
| **B5** — Chave de comunicação também é independente do segredo de propriedade | Confirmado | [security.py](../apps/api/app/security.py): Autenticação Device é separada do token de claim usado na vinculação. |
| **B6** — Banco armazena hashes de chave do dispositivo e claim | Confirmado | [models.py](../apps/api/app/models.py): Device.key_hash e DeviceClaim.token_hash persistem hashes; presence_secret tem outra finalidade e é segredo do servidor. |
| **B7** — Chave individual pode ser revogada ou rotacionada | Confirmado | [routes.py](../apps/api/app/modules/devices/routes.py): Rotação/revogação continuam disponíveis com autorização do proprietário. |
| **B8** — Equipamento provisionado começa inativo e sem dono | Confirmado | [provision_point.py](../tools/provision_point.py): Provisionamento cria equipamento inativo; publicação depende da configuração/vinculação. |
| **B9** — Claim pelo mesmo dono é idempotente; outro dono é recusado | Confirmado | [test_ownership.py](../apps/api/tests/test_ownership.py): Repetição pelo mesmo dono e tentativa por outro dono foram cobertas na suíte PostgreSQL aprovada. |
| **B10** — Declarar-se vendedor não concede acesso a posto alheio | Confirmado | [service.py](../apps/api/app/service.py): operator e owned conferem habilitação e owner_id do posto. |
| **B11** — JWT verifica assinatura, emissor, audiência e expiração | Confirmado | [security.py](../apps/api/app/security.py): Validação explícita de algoritmo, assinatura, emissor, audiência e expiração continua presente. |
| **B12** — Clientes passam pela API; há separação entre credencial de migração e execução | Com ressalva | [grant_runtime_role.sql](../apps/api/sql/grant_runtime_role.sql): Papel restrito e concessões existem, mas a configuração da credencial de produção não foi auditada; migrações passaram só no banco descartável. |
| **C1** — Estados `starting`, `charging`, `stopping` são diferentes | Confirmado | [models.py](../apps/api/app/models.py): Sessão mantém starting/charging/stopping e estados terminais distintos. |
| **C2** — `Idempotency-Key` combina operação, usuário e corpo | Confirmado | [service.py](../apps/api/app/service.py): Idempotência continua delimitada por usuário, operação, chave e hash do corpo. |
| **C3** — Mesma chave com conteúdo diferente gera conflito | Confirmado | [test_control.py](../apps/api/tests/test_control.py): Teste de chave repetida com corpo divergente passou na suíte da API. |
| **C4** — Travas transacionais serializam reservas concorrentes | Confirmado | [service.py](../apps/api/app/modules/reservations/service.py): Reserva passa por lock_point; corrida de reservas foi reexecutada com PostgreSQL. |
| **C5** — Índices únicos parciais reforçam reserva/sessão ativa por usuário e ponto | Confirmado | [models.py](../apps/api/app/models.py): Índices únicos parciais continuam protegendo usuário/ponto nas reservas e sessões ativas. |
| **C6** — Comandos têm versão e validade | Confirmado | [charging_controller.cpp](../firmware/esp32/src/charging_controller.cpp): Controlador recusa comandos antigos/expirados; caminho foi exercitado no host. |
| **C7** — Telemetria identifica dispositivo, boot e sequência | Confirmado | [models.py](../apps/api/app/models.py): Telemetria tem unicidade em dispositivo/boot/sequence e registro de boot. |
| **C8** — Replay não renova artificialmente o contato do dispositivo | Confirmado | [service.py](../apps/api/app/modules/devices/service.py): Replay é tratado antes de renovar contato/autorização. |
| **C9** — Energia cumulativa não pode regredir na atualização da sessão | Confirmado | [service.py](../apps/api/app/modules/devices/service.py): Sessão rejeita regressão de energia; agregação histórica trata reinício do contador separadamente. |
| **C10** — Eventos têm chaves únicas | Confirmado | [models.py](../apps/api/app/models.py): SessionEvent tem chave única por sessão; reentrega não duplica o mesmo fato. |
| **C11** — Horário de captura e de recebimento são distintos | Confirmado | [models.py](../apps/api/app/models.py): captured_at e received_at continuam campos diferentes da telemetria. |
| **C12** — Código temporário ambíguo exige seleção explícita | Confirmado | [test_presence_flow.py](../apps/api/tests/test_presence_flow.py): Colisão de código entre postos exige seleção; testes reexecutados com banco. |
| **D1** — Disponível considera teto contratado menos consumo da loja | Ajustado | [service.py](../apps/api/app/modules/power/service.py): Antes se destacava valor manual; agora site_inputs usa curva por perfil/porte e override simulado com TTL de 30 min. |
| **D2** — Há teto adicional dos carregadores do posto | Confirmado | [balancing.py](../packages/chargegrid_core/chargegrid_core/balancing.py): available intersecta limite efetivo da instalação com teto dos carregadores. |
| **D3** — Pedido respeita nominal, limite do ponto, motorista e equipamento | Confirmado | [balancing.py](../packages/chargegrid_core/chargegrid_core/balancing.py): Participant.request considera nominal, porta, carro e máximo declarado do equipamento. |
| **D4** — Só sessões participantes disputam a divisão | Confirmado | [balancing.py](../packages/chargegrid_core/chargegrid_core/balancing.py): A divisão continua por sessões participantes, sem diluir por conectores vazios. |
| **D5** — Sem capacidade para todos os pisos, chegada anterior tem prioridade | Confirmado | [balancing.py](../packages/chargegrid_core/chargegrid_core/balancing.py): Ordenação por chegada prioriza pisos anteriores; não é otimizador global ou garantia de equidade permanente. |
| **D6** — Firmware sem ajuste ao vivo é tratado como carga fixa | Confirmado | [service.py](../apps/api/app/modules/power/service.py): Ausência de set_power_v1 faz o equipamento entrar como carga fixa. |
| **D7** — Potência alvo, aplicada e estado ficam separados | Com ressalva | [service.py](../apps/api/app/modules/power/service.py): Alvo/aplicado são separados; aplicado é limite confirmado, distinto da potência instantânea medida e ainda simulado nesta bancada. |
| **D8** — Aumento usa a folga confirmada, incluindo comandos pendentes | Confirmado | [balancing.py](../packages/chargegrid_core/chargegrid_core/balancing.py): step usa envelopes e folga; teste de aumentos concorrentes passou na API. |
| **D9** — Redução sem confirmação é repetida uma vez; segunda falha leva a STOP | Com ressalva | [service.py](../apps/api/app/modules/power/service.py): Após duas reduções não confirmadas, after_sync emite STOP quando progride; não garante desligamento elétrico instantâneo nem execução sem novos syncs. |
| **D10** — Ponto offline mantém sua capacidade comprometida no cálculo | Confirmado | [service.py](../apps/api/app/modules/power/service.py): Envelope do ponto sem contato continua comprometido; ausência de rede não demonstra parada. |
| **D11** — Decisão registra entradas, motivo e eventual excesso transitório | Confirmado | [service.py](../apps/api/app/modules/power/service.py): PowerDecision registra entradas, hash, gatilho, resumo e exceeded_kw. |
| **D12** — Mesmo motivo aparece em versão longa e curta | Ajustado | [PowerCard.tsx](../apps/owner-web/src/components/station/PowerCard.tsx): Motivo continua no detalhe da estação/app/recibo; LivePanel da visão geral foi removido e sua referência estava quebrada. |
| **D13** — 0 W pausa a sessão sem acumular energia simulada | Confirmado | [charging_controller.cpp](../firmware/esp32/src/charging_controller.cpp): 0 W mantém sessão pausada, sem energia simulada; teste host passou. |
| **D14** — Watchdog de comunicação de 45 s e reboot sem retomada automática | Ajustado | [charger_link.h](../firmware/esp32/include/charger_link.h): Além de 45 s sem API, há perda de link em 5 s no painel e watchdog de 15 s no emulador; são trechos distintos. |
| **E1** — Tarifa pode variar por horário e demanda | Confirmado | [pricing.py](../packages/chargegrid_core/chargegrid_core/pricing.py): Tarifa base por horário e multiplicador de demanda continuam regras determinísticas. |
| **E2** — Intervalos sobrepostos são recusados, inclusive cruzando meia-noite e semana | Ajustado | [pricing.py](../packages/chargegrid_core/chargegrid_core/pricing.py): Agora só horários enabled participam da sobreposição; desligados podem se sobrepor sem valer na tarifa. |
| **E3** — Condições de preço são congeladas na reserva/início ou orçamento pago | Confirmado | [service.py](../apps/api/app/modules/charging/service.py): Reserva/início/orçamento pago preservam termos de preço aceitos. |
| **E4** — Cupom, base, multiplicador e motivo acompanham os termos | Confirmado | [receipt.py](../packages/chargegrid_core/chargegrid_core/receipt.py): price_terms continua com base, demanda, horário e cupom para explicar o recibo. |
| **E5** — Cupom ignora diferenças de maiúsculas/minúsculas | Confirmado | [service.py](../apps/api/app/modules/charging/service.py): find_coupon usa upper e valida dono/posto/validade. |
| **E6** — Dinheiro usa `Decimal` e regra explícita de arredondamento | Confirmado | [formatting.py](../packages/chargegrid_core/chargegrid_core/formatting.py): Decimal e ROUND_HALF_UP permanecem; regras de dinheiro passaram no core. |
| **E7** — Totais financeiros somam linhas arredondadas | Confirmado | [economics.py](../packages/chargegrid_core/chargegrid_core/economics.py): Agregação soma valores arredondados por linha; testes de fechamento passaram. |
| **E8** — Receita, comissão, tarifa do provedor, repasse e energia são separados | Confirmado | [Result.tsx](../apps/owner-web/src/pages/Result.tsx): Cascata diferencia receita, descontos, comissão, repasse e custo. |
| **E9** — Custo da energia ausente não vira zero | Confirmado | [economics.py](../packages/chargegrid_core/chargegrid_core/economics.py): Custo faltante produz margem None, incluindo cobertura incompleta do período. |
| **E10** — Margem negativa é preservada e pode gerar aviso | Confirmado | [economics.py](../packages/chargegrid_core/chargegrid_core/economics.py): Margem negativa é preservada; avisos não a truncam para zero. |
| **E11** — Recibo diferencia provisório e confirmado | Confirmado | [receipt.py](../packages/chargegrid_core/chargegrid_core/receipt.py): Recibo ainda distingue sessão em andamento e evidência de encerramento. |
| **E12** — Origem simulada/medida e bases estimadas aparecem no modelo | Com ressalva | [receipt.py](../packages/chargegrid_core/chargegrid_core/receipt.py): Rótulos de proveniência existem; transport=modbus_tcp no novo emulador não muda source=simulated para measured. |
| **E13** — Recarga concluída e veículo desconectado são estados distintos | Confirmado | [overstay.py](../apps/api/app/overstay.py): Carga concluída e cabo conectado continuam independentes no modelo; no protótipo a conexão é simulada. |
| **E14** — Permanência cobra só intervalos completos confirmados, com tolerância e teto | Confirmado | [overstay.py](../packages/chargegrid_core/chargegrid_core/overstay.py): Intervalo completo, tolerância e teto permanecem em cálculo puro. |
| **E15** — Lacunas offline não são cobradas como tempo comprovado | Confirmado | [overstay.py](../apps/api/app/overstay.py): Lacuna superior à evidência permitida não entra como conexão confirmada; testes API passaram. |
| **E16** — Sem versão de termos aceita, permanência pode ser registrada com taxa zero | Confirmado | [overstay.py](../apps/api/app/overstay.py): Sem versão aceita dos termos a permanência é registrada sem taxa. |
| **F1** — Gateway aceita somente chaves de teste Stripe | Com ressalva | [gateway.py](../apps/api/app/modules/payments/gateway.py): Somente prefixos de chave Stripe teste habilitam esse gateway; isso não certifica toda a segurança financeira do produto. |
| **F2** — Checkout é hospedada pelo provedor | Confirmado | [service.py](../apps/api/app/modules/payments/service.py): Checkout é hospedada; app não coleta número do cartão nesse fluxo. |
| **F3** — Retorno do navegador não confirma pagamento | Confirmado | [service.py](../apps/api/app/modules/payments/service.py): Retorno do navegador não basta; consulta/webhook assinado alteram confirmação. |
| **F4** — Captura/devolução usam idempotência | Confirmado | [gateway.py](../apps/api/app/modules/payments/gateway.py): Captura/devolução usam chave de idempotência; testes do gateway passaram. |
| **F5** — Cartão tem captura parcial; Pix pode devolver a diferença | Com ressalva | [billing.py](../packages/chargegrid_core/chargegrid_core/billing.py): Captura parcial no cartão e devolução Pix existem em teste; métodos dependem da configuração, não foram pagos externamente nesta revisão. |
| **F6** — Pagamento tardio após expiração não inicia automaticamente | Confirmado | [test_kiosk_totem.py](../apps/api/tests/test_kiosk_totem.py): Pagamento tardio após expiração tem tratamento de devolução; suíte API passou. |
| **F7** — Pedido aberto do totem bloqueia disputa do app pelo mesmo ponto | Confirmado | [service.py](../apps/api/app/service.py): Pedido aberto do totem cria hold e participa da disponibilidade do ponto. |
| **F8** — Orçamento do totem usa a regra comum de preço | Confirmado | [test_kiosk_totem.py](../apps/api/tests/test_kiosk_totem.py): Teste compara orçamento do totem ao app; passou com PostgreSQL. |
| **F9** — Método simulado/Stripe vem do servidor | Confirmado | [service.py](../apps/api/app/modules/kiosk_totem/service.py): Método vem do estado autorizado da conta/servidor, não de uma escolha livre do dispositivo. |
| **F10** — Pedido aberto fica na NVS para recuperação | Confirmado | [main.cpp](../firmware/esp32/src/main.cpp): Pedido kord é guardado/recuperado na NVS; controlador não retoma energização por isso. |
| **F11** — Mesmo no autoatendimento, START vem pelo fluxo autorizado normal | Confirmado | [kiosk_flow.cpp](../firmware/esp32/src/kiosk_flow.cpp): Pagamento confirmado aguarda START normal; host testou os dois modos. |
| **F12** — Histórico e exportações carregam canal e método | Confirmado | [test_kiosk_totem.py](../apps/api/tests/test_kiosk_totem.py): Origem e método chegam ao histórico/exportações; testes reexecutados. |
| **G1** — Ferramentas consultam dados, sem iniciar, parar, reservar ou cobrar | Confirmado | [tools.py](../packages/chargegrid_core/chargegrid_core/ai/tools.py): Catálogo de ferramentas é de consulta, com ações sugeridas encaminhando às telas normais. |
| **G2** — Identidade vem do usuário autenticado, sem `user_id` escolhido pelo modelo | Confirmado | [source.py](../apps/api/app/modules/ai/source.py): Fonte injeta usuário autenticado; modelo não seleciona outro titular por argumento. |
| **G3** — Indicadores de proprietário exigem permissão | Confirmado | [source.py](../apps/api/app/modules/ai/source.py): Consultas do dono verificam operator_enabled e owner_id. |
| **G4** — Botões são derivados de IDs retornados pelas ferramentas | Confirmado | [actions.py](../packages/chargegrid_core/chargegrid_core/ai/actions.py): Destinos derivam dos registros consultados e não apenas de texto livre. |
| **G5** — Fonte de leitura evita chamar conciliação que pode emitir comandos | Confirmado | [source.py](../apps/api/app/modules/ai/source.py): Fonte evita lock_point e rotinas de conciliação que podem emitir comando. |
| **G6** — Regras tratam nomes e endereços como dados não confiáveis | Com ressalva | [prompt.py](../packages/chargegrid_core/chargegrid_core/ai/prompt.py): Há regras e ensaios contra injeção; não se deve prometer resistência absoluta. |
| **G7** — Orçamento de tempo, rodadas, mensagens e chamadas é limitado | Confirmado | [loop.py](../packages/chargegrid_core/chargegrid_core/ai/loop.py): Rodadas, ferramentas, tamanho do histórico e orçamento de tempo continuam limitados. |
| **G8** — API encerra a transação antes de aguardar o provedor | Confirmado | [routes.py](../apps/api/app/modules/ai/routes.py): Wrapper complete chama db.commit antes da espera pelo provedor. |
| **G9** — Uso registra custo, latência e ferramentas, sem salvar perguntas e respostas nessa tabela | Com ressalva | [models.py](../apps/api/app/models.py): AiUsage guarda metadados, não perguntas/respostas; a inferência externa ainda recebe o contexto enviado. |
| **G10** — Falha do provedor tem fallback identificado | Confirmado | [routes.py](../apps/api/app/modules/ai/routes.py): Busca/insights podem usar regras; chat indisponível leva a orientação local identificada no app. |
| **G11** — Benchmark inclui português, ferramentas, ação e injeção | Com ressalva | [ia-openrouter.md](ia-openrouter.md): Benchmark é registro histórico de ensaio; não foi reexecutado e não prova custo/latência atuais do provedor. |
| **G12** — Chave externa fica no backend e demo local é excluída do APK | Confirmado | [pyproject.toml](../apps/mobile/pyproject.toml): Demo que consulta OpenRouter diretamente permanece excluída do pacote; app real usa API. |
| **H1** — Histórico por conector/hora é persistido | Confirmado | [models.py](../apps/api/app/models.py): ConnectorHourlyStats e AggregateWatermark continuam persistidos. |
| **H2** — Energia usa diferenças de contador cumulativo | Confirmado | [aggregate.py](../packages/chargegrid_core/chargegrid_core/forecast/aggregate.py): Agregação usa delta de telemetria e não soma acumuladores repetidos. |
| **H3** — Agregação trata regressão de contador e virada de hora | Confirmado | [aggregate.py](../packages/chargegrid_core/chargegrid_core/forecast/aggregate.py): Testes de regressão e cruzamento de hora passaram no core. |
| **H4** — Energia horária conserva o total final da sessão | Confirmado | [aggregate.py](../packages/chargegrid_core/chargegrid_core/forecast/aggregate.py): Total horário é reconciliado com energia da sessão; teste de conservação passou. |
| **H5** — Dados reais/simulados prevalecem sobre sintéticos na composição prevista | Confirmado | [series.py](../packages/chargegrid_core/chargegrid_core/forecast/series.py): Observação não sintética prevalece na mesma hora/conector; não converte origem simulada em medida. |
| **H6** — Seed sintético não cria sessões nem receita | Confirmado | [seed_forecast_history.py](../tools/seed_forecast_history.py): Seed grava agregados synthetic sem criar faturamento/sessões. |
| **H7** — Modelo é comparado com baseline histórico | Confirmado | [engine.py](../packages/chargegrid_core/chargegrid_core/forecast/engine.py): Motor mantém baseline e modelo como candidatos distintos. |
| **H8** — Avaliação separa períodos e inclui postos não vistos | Com ressalva | [previsao-ocupacao.md](previsao-ocupacao.md): Separação temporal e postos não vistos pertencem ao protocolo sintético offline, sem prova de desempenho de campo. |
| **H9** — Backtest do posto usa apenas passado e exige histórico suficiente | Confirmado | [evaluate.py](../packages/chargegrid_core/chargegrid_core/forecast/evaluate.py): Backtest usa histórico anterior e no mínimo sete origens válidas. |
| **H10** — Modelo só é escolhido com WAPE no máximo 95% do baseline | Confirmado | [evaluate.py](../packages/chargegrid_core/chargegrid_core/forecast/evaluate.py): MARGIN=0.95 continua critério de escolha, condicionado também à seleção offline. |
| **H11** — Faixa insuficientemente avaliada aparece como não calibrada | Confirmado | [Forecast.tsx](../apps/owner-web/src/pages/Forecast.tsx): Tela mantém faixa não calibrada quando faltam erros suficientes. |
| **H12** — Treino é offline; API avalia árvores exportadas em Python puro | Confirmado | [model_v1.py](../packages/chargegrid_core/chargegrid_core/forecast/model_v1.py): Árvores exportadas são Python puro; treino fica nas ferramentas. |
| **H13** — Previsão de energia usa a média porque ela foi melhor para esse objetivo | Com ressalva | [previsao-ocupacao.md](previsao-ocupacao.md): Uso da média para energia segue resultado do ensaio sintético, não superioridade universal. |
| **H14** — Sugestão de tarifa exige revisão do proprietário | Confirmado | [Forecast.tsx](../apps/owner-web/src/pages/Forecast.tsx): Aplicação de sugestão passa por estado pending e revisão do dono. |
| **H15** — Melhor horário explica preço estimado e ocupação | Com ressalva | [best_times.py](../packages/chargegrid_core/chargegrid_core/forecast/best_times.py): Melhor horário é estimativa; regra tarifária do momento e incerteza não garantem preço futuro. |
| **H16** — Manutenção respeita a marca da agregação antes de apagar telemetria | Confirmado | [maintenance.py](../tools/maintenance.py): Limpeza considera watermark e retenção; comportamento não depende de apagar sessões históricas. |
| **I1** — Visão geral reúne energia, receita, ocupação, reservas e não comparecimento | Confirmado | [Overview.tsx](../apps/owner-web/src/pages/Overview.tsx): KPIs continuam na visão geral, incluindo ocupação/reservas/não comparecimento. |
| **I2** — Mapa de calor e ranking mostram padrões por ponto e horário | Confirmado | [Overview.tsx](../apps/owner-web/src/pages/Overview.tsx): Mapa de calor e ranking continuam; cartão de status ao vivo saiu. |
| **I3** — Alertas levam à estação correspondente | Confirmado | [AlertRow.tsx](../apps/owner-web/src/components/AlertRow.tsx): Alerta mantém navegação/contexto da estação. |
| **I4** — Filtros de período/estação acompanham relatórios | Confirmado | [Result.tsx](../apps/owner-web/src/pages/Result.tsx): Exportação do resultado usa recorte selecionado; testes de filtros passaram. |
| **I5** — Períodos usam o fuso de São Paulo | Confirmado | [analytics.py](../packages/chargegrid_core/chargegrid_core/analytics.py): Fuso do relatório continua America/Sao_Paulo. |
| **I6** — Exportação CSV neutraliza fórmulas de texto | Confirmado | [analytics.py](../packages/chargegrid_core/chargegrid_core/analytics.py): CSV neutraliza células que poderiam ser interpretadas como fórmula. |
| **I7** — Datas ausentes, sem histórico e dados desconhecidos têm estados próprios | Confirmado | [format.ts](../apps/owner-web/src/lib/format.ts): Formatação distingue null/ausente de número zero; telas têm estados sem histórico. |
| **I8** — Edição do painel aguarda resposta do servidor | Confirmado | [StationDetail.tsx](../apps/owner-web/src/pages/StationDetail.tsx): onSaved adota resposta de salvamento; campo de carregador também espera servidor. |
| **I9** — Consultas simultâneas compartilham renovação de token | Confirmado | [client.ts](../apps/owner-web/src/api/client.ts): Refresh continua compartilhado entre requisições simultâneas. |
| **I10** — Queda de rede não é tratada automaticamente como logout | Confirmado | [client.ts](../apps/owner-web/src/api/client.ts): Falha de transporte é diferente de rejeição de credenciais. |
| **I11** — App pausa polling oculto e recua durante falhas | Confirmado | [app.py](../apps/mobile/src/chargegrid_app/app.py): Lifecycle pausa polling e falhas usam recuo; suíte de comportamento passou. |
| **I12** — Cache de leitura não substitui consultas de operações sensíveis | Confirmado | [api_cache.py](../apps/mobile/src/chargegrid_app/api_cache.py): Operações sensíveis não são servidas por cache de montagem de tela. |
| **I13** — Toque repetido e navegação durante ação pendente são controlados | Confirmado | [app.py](../apps/mobile/src/chargegrid_app/app.py): Controle de ações ativas impede toque duplicado e saída durante mutação. |
| **I14** — Formulário alterado pede decisão antes de descartar | Confirmado | [test_motion_navigation.py](../apps/mobile/tests/test_motion_navigation.py): Testes de descarte de formulário e manutenção dos campos passaram. |
| **I15** — Contraste ≥4,5:1 é testado em textos e badges compartilhados nos dois temas | Com ressalva | [test_brand_accessibility.py](../apps/mobile/tests/test_brand_accessibility.py): Teste 4,5:1 passou para componentes compartilhados; não cobre toda a interface/mapa nem certifica WCAG integral. |
| **I16** — Foco de teclado, semântica de aba e movimento reduzido têm tratamento | Com ressalva | [app.py](../apps/mobile/src/chargegrid_app/app.py): Semântica/foco/reduced motion existem; novos controles de mapa exigem avaliação integral própria. |
| **I17** — Mapa carrega depois do conteúdo e tem fallback esquemático | Ajustado | [vector_map.py](../apps/mobile/src/chargegrid_app/ui/vector_map.py): Fallback esquemático não descreve mais os mapas atuais; MapLibre usa tiles externos e oferece nova tentativa. |
| **I18** — Fontes web são locais e páginas carregam sob demanda | Confirmado | [App.tsx](../apps/owner-web/src/App.tsx): React mantém lazy routes e fontes locais; não confundir com glyphs/tiles externos do mapa do app. |
| **I19** — Mock web é condicionado a desenvolvimento e há verificação do build | Confirmado | [main.tsx](../apps/owner-web/src/main.tsx): Mock continua restrito a desenvolvimento; script de inspeção do build existe, sem novo build nesta revisão. |
| **I20** — APK tem consulta de versão e oferta de atualização | Confirmado | [updates.py](../apps/mobile/src/chargegrid_app/services/updates.py): Consulta de versão e oferta de download continuam; instalação depende do usuário. |
| **J1** — Painel sem configuração mostra estado de configuração, sem inventar ponto | Confirmado | [panel_ui.cpp](../firmware/esp32/src/panel_ui.cpp): Estados de fábrica/configuração continuam próprios, exercitados pelo host. |
| **J2** — Configuração de Wi-Fi mascara senha e não a envia ao log | Confirmado | [main.cpp](../firmware/esp32/src/main.cpp): Configuração de rede do painel não ecoa senha; testes do controlador/UI passaram. |
| **J3** — Limpar rede e trocar identidade são operações separadas | Confirmado | [main.cpp](../firmware/esp32/src/main.cpp): Limpeza de Wi-Fi preserva identidade; reset de propriedade é fluxo separado. |
| **J4** — Alterações sensíveis são bloqueadas durante estados incompatíveis | Confirmado | [main.cpp](../firmware/esp32/src/main.cpp): Manutenção sensível continua condicionada ao estado da sessão/reserva. |
| **J5** — Parada local não depende de abrir o app | Ajustado | [charging_controller.cpp](../firmware/esp32/src/charging_controller.cpp): Parada local em Modbus solicita STOP/releitura e repete se falhar; estado parado na tela não prova contato de relé aberto. |
| **J6** — Não há comando serial START de manutenção | Confirmado | [main.cpp](../firmware/esp32/src/main.cpp): Serial de manutenção do painel segue sem START; não confundir com ferramentas externas que podem escrever Modbus. |
| **J7** — QR de propriedade desaparece depois da vinculação | Confirmado | [firmware_behavior.cpp](../tools/tests/firmware_behavior.cpp): QR de claim some após posse; host e decodificador reexecutados. |
| **J8** — Testes decodificam QR realmente renderizado pelo LVGL | Confirmado | [validate_firmware.py](../tools/validate_firmware.py): QRs reais do LVGL foram decodificados novamente, inclusive ausência nos estados previstos. |
| **J9** — Scanner Android usa decodificação local e não exporta imagem | Com ressalva | [README.md](../apps/mobile/packages/chargegrid_scanner/README.md): Scanner Android é local e não exporta imagem; ensaio físico de câmera não foi refeito. |
| **J10** — Câmera começa por ação explícita e encerra antes de entregar a leitura | Com ressalva | [README.md](../apps/mobile/packages/chargegrid_scanner/README.md): Início explícito e encerramento antes do evento são contrato implementado; não houve novo ensaio em telefone. |
| **J11** — Cancelamento, retorno e permissão tardia liberam a câmera | Com ressalva | [README.md](../apps/mobile/packages/chargegrid_scanner/README.md): Cancelamento/lifecycle têm tratamento e testes prévios; suíte Flutter do scanner não foi reexecutada nesta rodada. |
| **J12** — Há alternativa de colar código em plataforma sem scanner | Confirmado | [ownership.py](../apps/mobile/src/chargegrid_app/screens/ownership.py): Colagem/manual continuam alternativa ao scanner indisponível. |
| **J13** — Fluxo do totem é C++ puro separado do desenho LVGL | Confirmado | [kiosk_flow.cpp](../firmware/esp32/src/kiosk_flow.cpp): Máquina de estados C++ continua separada dos widgets LVGL; host reexecutado. |
| **J14** — Telas do totem são criadas/liberadas conforme uso | Confirmado | [router.cpp](../firmware/esp32/src/ui/router.cpp): Telas são criadas/liberadas no roteamento; pico do pool medido no host novamente. |
| **J15** — Firmware novo reconhece campos recusados por API anterior | Confirmado | [api_client.cpp](../firmware/esp32/src/api_client.cpp): Fallback de campos para API antiga permanece; testes 422 passaram no host. |
| **J16** — Case do painel prevê USB, RESET/BOOT, ventilação e desmontagem | Com ressalva | [README.md](case-tela-waveshare-7/README.md): Portas/desmontagem/ventilação estão projetadas e documentadas; encaixe físico não conferido agora. |
| **J17** — Case foi dividido para o volume da impressora e tem amostras de encaixe | Com ressalva | [README.md](case-tela-waveshare-7/README.md): Divisão para volume de impressão e cupons existem; não foi reimpresso ou medido o case. |
| **J18** — Mini preserva a forma externa derivada do STEP e usa bandeja/berços substituíveis | Ajustado | [plano-prototipo-usb.md](plano-prototipo-usb.md): Mecânica modular permanece; firmware HCA/relé novo não comprova integração USB com controle variável nem montagem no case. |
| **J19** — Revisões mecânicas registram colisões, movimentos, perfis e hashes | Com ressalva | [REVISAO-FINAL-2026-10-15.md](prototipo-usb/ender3-pla-oficial-v9/REVISAO-FINAL-2026-10-15.md): Hashes e testes de movimento são evidências digitais históricas, sem nova auditoria de cada STL. |
| **J20** — Arquivos já impressos são preservados em revisões posteriores | Ajustado | [LEIA-PRIMEIRO.md](prototipo-usb/peca5-revisao-2026-10-21/ENTREGA/LEIA-PRIMEIRO.md): R10 substitui somente peça 5, mantém geometria e reduz retrações; relatório ainda diz impressão física não realizada. |
| **K1** — Regras de domínio puras ficam em pacote compartilhado | Com ressalva | [sync_core.py](../tools/sync_core.py): Regras Python são compartilhadas e cópias conferem; React/C++ também têm traduções próprias, não um único código literal para todas as plataformas. |
| **K2** — Cópias para app/API têm checagem de igualdade | Confirmado | [test_core_sync.py](../tools/tests/test_core_sync.py): Igualdade de todas as cópias Python passou na execução atual. |
| **K3** — Migrações versionam mudanças no banco | Confirmado | [c5e9a2d7f4b1_every_connector_is_a_goodwe_charger.py](../apps/api/migrations/versions/c5e9a2d7f4b1_every_connector_is_a_goodwe_charger.py): Cadeia de migrações foi aplicada até head em banco PostgreSQL novo e descartável. |
| **K4** — Consultas em lote e agregações SQL evitam N+1 | Confirmado | [test_query_budget.py](../apps/api/tests/test_query_budget.py): Testes de orçamento de consultas passaram com PostgreSQL; não é benchmark de throughput de produção. |
| **K5** — Testes cobrem concorrência, repetição e comunicação perdida | Ajustado | [test_control.py](../apps/api/tests/test_control.py): Agora a suíte completa da API foi reexecutada: 425 aprovados, incluindo caminhos de concorrência/replay. |
| **K6** — Teste de importação exige nome de banco descartável | Confirmado | [test_admin_tools.py](../tools/tests/test_admin_tools.py): Proteção de nome de banco nos testes destrutivos continua presente; essas ferramentas de importação não foram executadas contra bancos existentes. |
| **K7** — CI configura API/PostgreSQL, app, core, scanner e firmware | Ajustado | [ci.yml](../.github/workflows/ci.yml): Workflow cobre bases anteriores; ainda não inclui React, Flutter do mapa ou target de firmware goodwe-hca-sim. |
| **K8** — Simulador de dispositivo usa o contrato de sincronização | Confirmado | [device_simulator.py](../tools/device_simulator.py): Simulador segue o contrato atual e escolhe modo no START; testes selecionados passaram. |
| **K9** — Empacotamento exclui `.env`, testes e prévia de IA do APK | Confirmado | [pyproject.toml](../apps/mobile/pyproject.toml): Exclusões de env/testes/demo AI continuam; não foi inspecionado um APK recém-compilado nesta revisão. |
| **K10** — Dados fictícios e artefatos de provisionamento têm tratamento separado | Confirmado | [provision_point.py](../tools/provision_point.py): Artefatos de provisionamento permanecem privados e separados de demonstração pública. |

## Novidades que mais merecem espaço na apresentação

1. **Dois firmwares com responsabilidades distintas:** painel mestre e emulador do carregador, ligados por Modbus TCP local.
2. **Modo fixado no início da sessão:** carregador online usa Modbus; ausente usa simulação interna. Aparecer depois não muda aquela sessão.
3. **Endereço protegido:** obrigatório, único no posto, preenchido pelo banco e bloqueado para troca durante uso.
4. **Consumo predial com comportamento:** perfil, porte, calendário e janelas reproduzíveis; valor manual expira.
5. **Horário tarifário ativável:** desliga sem apagar, com verificação de conflito ao reativar.
6. **Mapa vetorial de verdade:** preserva câmera/seleção, atualiza marcadores sem remontar e mantém créditos acessíveis.
7. **Entrega Android verificada:** regra R8 e inspeção da fábrica JNI do mapa no APK, sem alegar que isso substitui teste em aparelho.
8. **Correção mecânica localizada:** R10 da peça 5 preserva geometria e demais peças, com estimativas/documentação próprias.

O catálogo L1–L30 do guia traz as frases curtas e os limites de cada novidade.

## Pendências que a análise não deve esconder

- As duas falhas de expectativas do app e os avisos de depreciação.
- CI ainda sem React, testes Flutter do mapa ou build do firmware HCA novo; o build firmware existente usa o target base por padrão.
- Mapas, pacote local e ferramentas de release ainda estão como alterações locais/não rastreadas nesta revisão; só o commit não reproduz essa versão.
- Guias antigos ainda misturam limite de reserva 10/15 min, sync 5/10 versus 1/5 s e promessa antiga de gateway futuro. O guia de apresentação foi corrigido, os demais foram preservados.
- O próprio guia do emulador começa descrevendo WROOM/LED GPIO2, mas o target S3 novo usa `CG_LED_PIN=-1` e serial pela ponte UART, sem LED dedicado.
- O tipo/porte e limite padrão são hipóteses explícitas de simulação, não laudo, medição ou dimensionamento da instalação. O teto de 85% preserva uma fração do limite, mas por si só não garante o piso de qualquer carro para todo limite configurável.
- A unicidade de endereço é por posto no banco. Dois postos independentes na mesma LAN com emuladores `cg-hca-1.local` podem conflitar em mDNS; a unicidade da LAN inteira não é garantida por essa restrição.
- ACK/releitura valida registradores, não contato físico do relé, corrente do telefone ou segurança elétrica certificada.
- Relatórios de impressão R10 e recibo de SD são evidências documentais; não houve impressão ou leitura do cartão nesta tarefa.
- Sem ensaio novo em câmera, mapa/telefone, ESP32, relé, Stripe externo ou HCA G2 comercial; sem deploy ou migração na nuvem.

Não foram feitas novas afirmações de conformidade elétrica, jurídica, licenciamento cartográfico, compatibilidade comercial ou desempenho de campo a partir desses dados locais.
