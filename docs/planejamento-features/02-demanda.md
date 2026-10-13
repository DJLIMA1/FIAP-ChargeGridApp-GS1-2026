# Gestão agregada de demanda e balanceamento

Planejamento de 1 de outubro de 2026. Este documento propõe implementação futura; não confirma atuação em carregador de veículo. O primeiro ciclo utiliza simulação por código, sem RFID e sem separação solar/rede. A fronteira futura SEMS+ depende de documentação, acesso autorizado e capacidades confirmadas, conforme [01-simulacao-sems.md](01-simulacao-sems.md).

## Estado atual e oportunidade

O [relatório dos pitches](../analise-pitches-goodwe-fiap-2026.md) identifica demanda como pergunta recorrente da banca. A vantagem pretendida é demonstrar limite, decisão, aplicação e resultado, explicando também quando o pedido não pode ser atendido.

Hoje, `Connector.power_kw`, em `apps/api/app/models.py`, representa potência cadastrada; não constitui comando aplicado. `apps/api/app/modules/charging/service.py` cria sessões com duração, orçamento e tarifa congelada e emite `START`. Não existe modelo de instalação, circuito ou alocação agregada.

`firmware/esp32/src/sensors.cpp` gera 7.200 W durante carga, acumulando energia e SoC simulados. `charging_controller.cpp` também usa 7.200 W no cálculo do tempo restante até o orçamento. Esse cálculo precisa acompanhar a potência efetivamente simulada. O protocolo em [esp32-protocol.md](../esp32-protocol.md) já possui IDs, versões, ACK e watchdog de 45 segundos; não possui ajuste de potência. `devices/service.py` verifica ACK junto do estado físico. `service.py::issue()` substitui comandos pendentes e incrementa uma versão global por ponto: adicionar comandos sem coordenação poderia invalidar um `START` ou `STOP`.

## MVP determinístico

Criar controlador no backend, compartilhado pelo aplicativo e pelas ferramentas MCP. A IA explica decisões e consulta fatos; não determina limites elétricos. Cada instalação tem teto, margem, consumo do prédio sem carregadores e circuitos. Medir consumo total incluindo carregadores e subtraí-los novamente seria dupla contagem: a fronteira da entrada precisa ser explícita.

Todos os cálculos internos usam W e Wh, com arredondamento conservador. A interface converte para kW/kWh. A capacidade da instalação é:

`C = max(0, teto_instalacao_w − consumo_predio_w − margem_w)`

Cada circuito tem teto próprio; cada ponto, máximo nominal, mínimo operacional e perfil de restrições. A soma das alocações deve respeitar simultaneamente instalação e circuitos. A potência solicitada nunca supera nominal, limite autorizado do veículo simulado ou limite do circuito. Abaixo do mínimo, o ponto deve aguardar ou pausar, conforme capacidade negociada; não inventar funcionamento em potência incompatível.

O MVP usa distribuição igual limitada pelos máximos: atribuir o mínimo a participantes selecionados e repartir o restante por preenchimento progressivo. Pontos que atingem seu máximo saem da distribuição; o excedente é repartido entre os demais. Empates usam ordem persistente de espera e ID, garantindo reprodução.

Quando a capacidade não atende todos os mínimos, selecionar quem está há mais tempo sem receber potência e alternar janelas configuráveis. Contabilizar tempo sem atendimento; registrar a razão de cada espera. Respeitar permanência mínima e rampas do perfil para evitar alternância excessiva. O perfil inicial é padrão. Perfis flexível/urgente podem entrar depois, com pesos limitados e envelhecimento da espera; urgência não supera segurança nem elimina atendimento dos demais. Preferência não implica preço adicional automático.

Limites por fase e corrente não são inferidos apenas de kW. O cenário inicial deve declarar circuito monofásico simulado ou pontos balanceados com restrições conhecidas. Perfis heterogêneos exigem verificação por fase no alocador. Configuração ausente impede ativar controle nesses perfis; a futura integração física requer parâmetros elétricos verificados.

## Estados, comando e transição

Contrato alinhado com a frente de simulação:

| Conceito | Campo proposto | Evidência |
| --- | --- | --- |
| Desejado | `desired_power_w` | Decisão do controlador; não prova atuação. |
| Aplicado | `applied_power_w` | Limite instalado e associado ao comando confirmado. |
| Observado | `power_w` | Potência produzida pelo simulador, podendo ser menor. |

Propor `SET_POWER_LIMIT`, com `parameters.power_limit_w`, mantendo `id`, `version`, `expires_at` e `session_id`. Negociar `set_power_limit_v1`; firmware sem essa capacidade não recebe o comando. ACK `received` não libera capacidade. ACK `applied` só é aceito com sessão/versão corretas, `last_power_command_id` correspondente e `applied_power_w` normalizado igual ao autorizado. A observação pode ficar abaixo do limite; ultrapassá-lo gera divergência e tratamento de falha.

`START` de simulador capaz recebe limite inicial em `parameters.power_limit_w`, instalado antes de energizar. A capacidade dessa partida é reservada antes do envio. Não emitir ajustes durante comando de ciclo de vida pendente; `STOP` tem precedência e nunca é substituído por um ajuste. Alterações frequentes são condensadas na próxima decisão, preservando idempotência e versões.

Reduzir primeiro; aguardar confirmação compatível; só então aumentar outro ponto. Não redistribuir a capacidade de uma redução pendente ou de um ponto desconectado. Para envelopes conservadores, reservar o maior limite que ainda pode estar aplicado, incluindo aumento autorizado em trânsito. Redução desejada não reduz esse envelope até confirmação.

`pause_session_v1` permite limite zero, preservando `session_id`, `connected=true` e `physical_state=charging`, com energia constante e indicação de pausa na UI. A duração continua contando. Sem essa capacidade, `STOP` encerra a sessão; não retomar silenciosamente. Pontos legados em carga são tratados como consumidores fixos na potência nominal, até comprovação de parada.

## Regra reproduzível e exemplo

```text
sob lock da instalação e dos circuitos, numa ordem fixa:
  validar versão da configuração e idade das entradas
  calcular C; descontar envelopes de cargas fixas/desconhecidas
  selecionar participantes respeitando mínimos, circuitos e espera
  repartir restante igualmente até máximos e restrições por fase
  registrar snapshot, decisão e motivos
  emitir reduções; manter capacidade anterior reservada
  após ACK + estado compatíveis, admitir aumentos e partidas
```

Exemplo inteiramente simulado: teto de 30 kW, prédio de 18 kW, margem de 2 kW e circuito de 12 kW. Sobram 10 kW. Três pontos de máximo 7,2 kW e mínimo didático configurado de 1,4 kW recebem aproximadamente 3,333 kW cada, arredondados para baixo. Sem controle, 21,6 kW dos pontos mais 18 kW do prédio totalizariam 39,6 kW. Com aplicação confirmada, o total fica aproximadamente 28 kW.

Se o prédio sobe para 25 kW, sobram 3 kW: dois pontos podem receber 1,5 kW e o terceiro aguarda, alternando pela regra de justiça. Se um ponto legado ainda consome 7,2 kW, o cenário é inviável nessa condição: solicitar parada e alertar, sem fingir que foi aplicada. Se o prédio sozinho excede o teto, o controlador dos carregadores não resolve essa sobrecarga.

Distribuir potência reduz pico ou desloca consumo no tempo; não demonstra redução dos kWh necessários. Energia entregue e SoC continuam simulados. Os números não são mínimos de um equipamento real.

## Contratos e persistência propostos

Criar `InstallationPolicy` com proprietário, `station_id`, teto, margem, versão e vigência; `CircuitPolicy` com teto e restrições por fase; `BuildingLoadSample` com valor, origem, `captured_at`, `received_at` e fronteira; `AllocationDecision` com algoritmo, snapshot, validade e motivos por ponto. Uma instalação inicialmente pode corresponder a um posto, permitindo expansão sem misturar medidores.

Guardar limite mínimo/máximo, capacidade de pausa, rampa e configuração de fases por perfil. Decisões devem registrar envelopes reservados e comandos emitidos, distinguindo proposta de confirmação. Evitar depender somente de `Telemetry`: o serviço atual conserva amostras aproximadamente a cada 30 segundos ou eventos; controle de cinco segundos precisa de snapshot validado mais recente.

Disparar decisões por nova entrada, ACK ou alteração de sessões, com verificação periódica de validade por executor durável. Não depender de tarefas em memória do processo HTTP. Como `sync()` atualmente bloqueia primeiro o conector, agendar a decisão após confirmar sua transação; o executor usa ordem de locks instalação/circuitos/pontos e verifica a versão do snapshot antes de enviar comandos, evitando inversão de locks e decisões concorrentes antigas.

Endpoints propostos: configuração e simulação restritas ao proprietário; consulta de alocação agregada pelo operador; consulta do motivo da própria sessão pelo motorista. MCP usa esses serviços com o mesmo controle de acesso, incluindo no endpoint público autenticado. Modelo gratuito OpenRouter intercambiável não altera regras nem obtém credenciais de dispositivo.

## Falhas, orçamento e estimativas

Adotar validade configurável por entrada, inicialmente 15 segundos para carga base simulada, além do estado online atual. Conferir captura e recepção; replay não renova validade. Entrada antiga implica nenhuma nova partida/aumento, pedido de redução segura e alerta. Reservar envelopes desconhecidos até reconciliação; ausência de dados nunca comprova potência zero.

Comandos falhos/expirados mantêm reserva conservadora, geram decisão degradada e tentativas limitadas. Reboot segue a parada/reconciliação atual. Saltos de consumo do prédio podem ultrapassar o teto durante a latência: registrar violação e duração, sem prometer proteção elétrica instantânea. Margem e frequência precisam corresponder à dinâmica simulada; integração física exigirá proteção apropriada.

Orçamento e duração permanecem limites independentes da potência. Alterar potência modifica a estimativa de energia até o prazo, preservando tarifa aceita e cupom. Campo futuro `requested_energy_wh`/`departure_at` permite avaliar viabilidade pela capacidade e energia restante, indicando hipótese e alternativas. Não garantir entrega nem inferir carga da bateria. Tarifação recebe condição de demanda para ofertas futuras; não reajusta sessão vigente automaticamente.

## Etapas, aceite e demonstração

1. Modelar políticas e snapshots; implementar alocador puro e cenários reproduzíveis.
2. Integrar simulador capaz, limite inicial no `START`, ACK e reserva de envelopes; preservar recuperação.
3. Exibir alocação, origem, validade, confirmação e motivo no operador/motorista; atualizar estimativas.
4. Acrescentar metas por prazo e perfis; avaliar justiça antes de previsão ou integração SEMS+.

Aceite: soma estável aplicada respeita tetos/circuitos; aumentos nunca usam redução não confirmada; partida não passa pelo nominal; replay e concorrência não duplicam comandos; falha não libera capacidade; legados não recebem comando incompatível; pausa respeita capacidade; ninguém aguarda indefinidamente em cenário estável com capacidade suficiente; orçamento é respeitado na integração da potência variável; violações transitórias aparecem explicitamente.

Demo: três sessões, gráfico identificado como simulado, aumento do prédio e redistribuição confirmada. Derrubar comunicação de um ponto, mostrar capacidade ainda reservada, watchdog e reconciliação. Encerrar com comparação usando as mesmas entradas: pico, tempo acima do teto, espera e energia simulada. Questões para a implementação: configuração elétrica do cenário, tamanho da margem, validade das entradas, janela de justiça e escopo da primeira meta por prazo.
