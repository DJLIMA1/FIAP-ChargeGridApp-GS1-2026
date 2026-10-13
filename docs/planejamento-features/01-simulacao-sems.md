# Medição e controle simulados, com fronteira futura para SEMS+

Data: 01/10/2026. Estado: planejamento; nenhum código, migração, ensaio ou integração externa foi executado nesta frente.

## Objetivo e limites

Transformar a bancada de potência fixa em uma simulação reproduzível de carregamento, capaz de receber limites de potência, confirmar a aplicação e produzir energia coerente. Essa base permitirá demonstrar balanceamento, cobrança estimada e recuperação de falhas. Preparar uma interface de integração com equipamentos sem afirmar que o ChargeGrid já conversa com SEMS+.

RFID e separação solar/rede ficam fora do escopo por decisão do usuário. A identificação por QR/código existente permanece suficiente. A integração futura não autoriza inventar endpoints GoodWe nem usar credenciais de instalador de maneira informal. O chat OpenRouter e o MCP público seguro consumirão serviços do ChargeGrid; não terão acesso direto ao simulador, às chaves dos pontos ou ao fornecedor.

## Estado atual observado

- [README](../../README.md) identifica corretamente a bancada simulada, com sincronização a cada 5 segundos em recarga e 10 segundos nos demais estados. O watchdog local é de 45 segundos; o servidor não considera falta de comunicação uma confirmação de parada.
- [Sensores C++](../../firmware/esp32/src/sensors.cpp), linhas 3–7, integram energia a 7.200 W constantes. O SoC é uma curva fictícia iniciada em 20%, sem modelo de veículo.
- [Controlador](../../firmware/esp32/src/charging_controller.cpp), linhas 43–63, limita energia por duração, comunicação e orçamento. O cálculo de tempo restante para o orçamento também contém 7.200 W fixos. Tornar apenas o sensor variável produziria uma parada financeira incorreta.
- Hoje os sensores vinculam conexão ao estado de carga e os simuladores desconectam ao executar STOP. Isso impede demonstrar permanência após o fim; conexão independente será uma capacidade simulada explícita, coordenada com [notificações e overstay](06-notificacoes-overstay.md).
- [Simulador Python](../../tools/device_simulator.py), linhas 19–165, já injeta relógio monotônico, persiste energia e comandos e respeita watchdog, orçamento e replay. Potência, timestamp UTC e expiração de reserva ainda não usam uma abstração inteiramente determinística.
- [Protocolo atual](../esp32-protocol.md) já oferece origem `simulated/measured/estimated`, energia acumulada em Wh, potência em W, `boot_id`, sequência e ACK `received/applied/failed`. A energia final é normalizada e imutável após encerramento.
- [Serviço de dispositivos](../../apps/api/app/modules/devices/service.py) rejeita regressão energética e confirma comandos pelo estado compatível. Comandos compartilham uma versão por ponto: uma atuação de potência não pode substituir inadvertidamente START ou STOP pendente.

O nominal cadastrado em `Connector.power_kw` não determina a potência atual de 7.200 W. Essa divergência deve aparecer na configuração da simulação e deixar de influenciar previsões silenciosamente.

## MVP e contratos propostos

Manter o caminho integrado app → API → dispositivo, substituindo somente o comportamento do equipamento capaz. Usar W e Wh no contrato de dispositivos; converter kW/kWh exclusivamente nas fronteiras de cadastro e apresentação.

| Campo | Semântica proposta |
| --- | --- |
| `source` | Origem da medição; neste MVP sempre `simulated`. |
| `nominal_power_w` | Teto configurado do dispositivo simulado. |
| `desired_power_w` | Limite solicitado pela política; pertence ao estado de controle da API. |
| `applied_power_w` | Limite efetivamente instalado e confirmado pelo dispositivo. |
| `power_w` | Potência observada, preservando o nome atual; pode ficar abaixo do aplicado. |
| `energy_wh` | Energia acumulada da sessão, monotônica, com três casas decimais. |
| `last_power_command_id` | Comando cujo limite está aplicado; correlaciona ACK e leitura. |
| `boot_id`, `sequence`, `captured_at` | Identidade do boot, ordem da leitura e tempo da captura. |
| `received_at` | Tempo de recebimento controlado pela API, usado para frescor. |
| `adapter_kind` | Origem da conexão: simulador, painel ou futuro provedor; não substitui `source`. |

Campos novos serão opcionais numa extensão negociada. Acrescentar `capabilities` com `set_power_limit_v1` e, separadamente, `pause_session_v1`. API anterior continua recebendo o corpo original; firmware anterior continua recebendo comandos que compreende. Publicar versão da extensão e matriz de compatibilidade antes de ativá-la.

O comando proposto `SET_POWER_LIMIT` reutiliza ID, versão, prazo e `session_id`; `parameters.power_limit_w` deve estar entre zero e o nominal. `received` confirma recepção; `applied` somente confirma o limite instalado. A API exige leitura compatível, `last_power_command_id` correspondente e valor aplicado autorizado. Potência observada abaixo do limite não significa falha, pois pode haver redução simulada da demanda do veículo. Potência acima do limite exige alerta e investigação.

START de um dispositivo capaz também carrega o limite inicial em `parameters.power_limit_w`, aplicado antes do início. Isso evita começar no nominal enquanto aguarda um segundo comando. STOP tem precedência; não emitir alocações enquanto START/STOP/RELEASE ou reconciliação estiverem pendentes. Coalescer pedidos de potência, evitando filas de versões obsoletas.

Zero mantém a sessão e a conexão somente com `pause_session_v1`: potência e energia deixam de crescer, e a interface informa pausa. Sem essa capacidade, a operação disponível é STOP terminal; não prometer retomada automática. Um dispositivo legado é tratado como carga fixa conservadora, nunca como carga reduzida por um comando desconhecido.

Separar `connected` de potência e término nos simuladores capazes: STOP interrompe energia, mas pode preservar a conexão até um evento de desconexão simulada. Oferecer dois cenários explícitos, desconectar ao terminar ou permanecer conectado. A API já permite confirmar STOP com estado terminal sem exigir `connected=false`; disponibilidade exige desconexão e as demais condições atuais. Pausa de balanceamento não é fim e não inicia overstay. Cabo desconectado não comprova que a vaga de estacionamento ficou vazia; origem e capacidade de observação precisam acompanhar esse proxy. No reboot, se a continuidade da conexão não puder ser comprovada, informar estado desconhecido para observação de permanência, sem inventar duração.

## Modelo determinístico e falhas

Criar um modelo com perfil nominal, aceitação do veículo, SoC inicial opcional e limite aplicado. No cenário simples, potência observada é o menor desses tetos e energia cresce por `W × segundos / 3600`. Integrar por trechos quando um comando muda o limite; energia anterior não pode ser recalculada. Para a primeira entrega, evitar ruído aleatório e curvas complexas. Um perfil opcional de redução perto do fim pode vir depois.

O relógio de cenários deve oferecer tempo monotônico e UTC coerentes; custo, energia, expiração e watchdog usam a mesma linha temporal. Avanço acelerado serve ao motor isolado e aos testes futuros. A demonstração integrada mantém tempo real: timestamps artificiais não devem ultrapassar a tolerância da API nem antecipar vencimentos no servidor.

Manter sync 5/10 segundos e watchdog 45 segundos inicialmente. Não reduzir esses prazos para impressionar na apresentação. Injetar cenários explícitos: ACK perdido, comando rejeitado, atraso, perda de rede, conexão removida, leitura obsoleta e reboot. Repetir comando não altera energia nem inicia duas sessões. Uma falha simulada muda estado e motivo, sem transformar timeout remoto em prova física.

Reboot desliga a atuação, preserva a energia final e exige nova autorização após conciliação. Revisar persistência: o firmware salva periodicamente, enquanto a API pode ter recebido leitura mais recente. O MVP precisa de checkpoint durável antes de publicar energia, com estratégia que considere desgaste da memória, para evitar regressão após reinício. Não resolver divergências inventando energia; manter o resultado pendente para reconciliação. Python e C++ compartilham contratos e cenários de referência, sem tentar compartilhar diretamente código entre runtimes.

## Fronteira SEMS+ e evidência primária

A GoodWe apresenta SEMS+ como gestão unificada com visibilidade e controle de ativos. Isso descreve seu produto; não comprova acesso externo aos comandos de um carregador específico. [Anúncio oficial de SEMS+, 06/01/2026](https://en.goodwe.com/goodwe-unveils-next-generation-sems-see-your-energy-in-a-new-light).

O documento público GoodWe API de 2024 distingue OpenAPI, monitoramento de dados e controle remoto. A modalidade de monitoramento citada exige credenciamento, licenciamento, whitelist e autorização do usuário; não faz controle remoto. O texto concentra essas modalidades em inversores e não demonstra START/STOP ou limite de potência para HCA via SEMS+. Essas condições precisam de confirmação atual. [Documento técnico GoodWe API](https://community.goodwe.com/static/images/2024-08-20597794.pdf). Existe também um [portal oficial OpenAPI](https://openapi.goodwe.com/), cuja disponibilidade não elimina a necessidade de documentação e autorização.

Propor `ChargerAdapter` com consulta de capacidades, leitura normalizada, envio de comando e consulta do resultado. `SimulatedAdapter` funciona primeiro; um adaptador futuro GoodWe permanece indisponível, retornando capacidade não habilitada. Não criar URLs fictícias ou fallback silencioso para simulação ao selecionar provedor real.

Pendências externas: modelo/firmware alvo, conta e região autorizadas, documentação vigente para carregadores, unidades, resolução, limites de chamadas, latência, estados de comando, consentimento e revogação. Medidor cumulativo do fornecedor exige baseline por sessão e tratamento de reset; origem cloud não torna SoC ou energia automaticamente medidos. O controle de proteção elétrica continuará pertencendo ao equipamento, conforme recursos homologados.

## Fases, arquivos e dependências

1. **Motor e cenários:** propor `tools/charging_simulation.py` e fixtures de perfis; adaptar `tools/device_simulator.py` com seleção explícita de cenário. Primeira validação isolada de energia e relógio.
2. **Atuação integrada:** evoluir `apps/api/app/schemas.py`, `models.py`, `modules/devices/service.py` e o emissor em `service.py`; planejar migração dos campos efetivamente persistidos. Evoluir `docs/esp32-protocol.md` e negociação de capacidades.
3. **Paridade da bancada:** adaptar `sensors.h`, `sensors.cpp`, `charging_controller.cpp` e sincronização do firmware; remover 7.200 W do cálculo de limite de custo. Exibir origem e potência aplicada/observada no app e painel.
4. **Adaptadores:** propor `apps/api/app/modules/devices/adapters/contracts.py` e adaptador simulado; iniciar fornecedor somente após documentação e acesso oficial. O painel mantém seu transporte atual.

A frente de demanda usa potência aplicada e frescor da telemetria. Não liberar orçamento elétrico só porque desejou reduzir outro ponto: aguardar ACK e leitura compatível. Pagamento e exportação recebem energia final e origem; MCP chama os mesmos serviços autorizados, sem regra duplicada de atuação. Nomes acima são propostas de implementação, não arquivos criados nesta etapa.

## Aceites e demonstração

Critérios futuros: energia correta com potência variável; limite inicial antes de carregar; redução e pausa confirmadas; duplicatas idempotentes; nominal respeitado; orçamento e duração corretos com potência variável; fim ainda conectado sem disponibilidade falsa; desconexão independente; pausa sem overstay; watchdog cortando no instante previsto; reboot sem retomada nem regressão; isolamento entre dispositivos; firmware legado compatível; origem simulada visível em histórico e exportações. Planejar casos no simulador, contrato da API e bancada do firmware existentes; nenhum foi executado para este plano.

Demo: dois pontos simulados iniciam com limites autorizados; o consumo do prédio aumenta; a API solicita redução, mostra pendência e só confirma após ACK. Energia passa a crescer mais lentamente. Um ponto perde comunicação, interrompe localmente aos 45 segundos e concilia o final ao retornar. Encerrar mostrando histórico com origem simulada e explicar a fronteira preparada para o acesso oficial SEMS+, sem alegar integração pronta.
