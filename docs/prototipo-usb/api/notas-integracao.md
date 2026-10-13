# API de referência do ChargeGrid Mini — perfil TPS25810 não selecionado

Revisão: 5 de outubro de 2026. **O usuário passou a exigir módulos prontos, sem laboratório nem montagem SMD. A rota com TPS25810 e INA260 avulsos foi excluída da seleção.** Este diretório preserva um contrato de referência dessa rota, não o contrato definitivo da fonte pronta ainda a escolher. Os perfis de 1,5/3 A e os sinais TPS abaixo não se aplicam automaticamente a um módulo ou carregador comercial. Liga/desliga isoladamente foi rejeitado como solução final.

Atualização em 7/10: compatibilidade com qualquer celular USB-C. A [direção vigente](../compatibilidade-usb-c.md) estuda capacidades Type-C de 1,5/3 A em 5 V, sem selecionar a placa histórica. Isso não libera os perfis do OpenAPI para operação. A API precisa distinguir capacidade aplicada de consumo medido e não pode prometer variação da velocidade em todos os aparelhos.

O documento não contém firmware, servidor em execução ou integração concluída. O painel, o backend e o aplicativo existentes foram apenas lidos. O novo carregador continua separado, com seu próprio ESP32-WROOM e firmware. As regras de sessão, idempotência, autorização temporal e energia medida podem ser reaproveitadas após a seleção do hardware; os controles elétricos precisam corresponder às funções reais da fonte escolhida. O contrato não representa uma API oficial GoodWe/SEMS nem compatibilidade OCPP.

O arquivo `openapi.json` usa OpenAPI 3.1 e define cinco caminhos: capacidades, estado, envio de comandos, consulta de comando e consulta de sessão. O perfil elétrico aqui estudado usa TPS25810 e INA260 e dependeria de PCB, montagem e ensaios, contrariando a nova restrição de módulos prontos. Por isso o exemplo começa com `operational=false`, `supported_current_limits_ma=[]` e `validation_state=not_validated`. Os demais exemplos são números fictícios para explicar o formato, nunca medições deste protótipo. As seções elétricas seguintes documentam exclusivamente esse perfil de referência, agora não selecionado.

## Separação entre os sistemas

O código atual em `firmware/esp32` reúne painel, sincronização com o backend e simulação. `src/sensors.cpp` fornece 7.200 W durante a simulação e inventa a progressão de SoC; `src/charging_controller.cpp` aplica comandos e persiste sessão/energia; `src/api_client.cpp` publica a telemetria em `/v1/devices/sync`. Esses comportamentos permanecem intactos nesta entrega.

A integração futura deve introduzir um adaptador explícito entre o controlador atual e esta API local. O painel continua responsável por apresentação, autorização comercial e conversa com o backend. O carregador recebe comandos locais, executa a saída USB, mede a energia e impõe suas próprias condições de parada. Nenhuma reserva, tarifa, cupom, usuário, senha de usuário ou token de ownership precisa residir no carregador.

| Camada existente | Contrato do novo carregador | Trabalho futuro necessário |
| --- | --- | --- |
| `START`, UUID de sessão e ACK `received/applied/failed` | `start`, mesmo UUID de sessão e resultado consultável | Adaptador grava a relação entre UUID do comando do backend e UUID local; não envia ACK aplicado antes da evidência física |
| `STOP` | `stop` prioritário | Confirmar saída desligada e conservar energia final antes de reconciliar |
| `RESERVE` / `RELEASE` | Sem comando equivalente | Reserva é estado de negócio do painel/backend; não habilita USB |
| `physical_state=charging` | `state=energized` com presença e VBUS confirmados | A correspondência exige sessão autorizada, `output_state=on` e presença `attached`; consumo pode ser zero |
| `connected` booleano | `phone_presence=attached/detached/unknown` | O backend atual não aceita desconhecido; ampliar o contrato ou manter presença separada antes da integração |
| `energy_wh`, `power_w`, `source` | Energia real e potência assinada medidas na porta | Remover a geração simulada apenas no futuro adaptador selecionado; nunca multiplicar os valores para parecer um carro |
| `soc_percent` | Sempre `null` | Não existe leitura da bateria do celular nesta arquitetura |
| Sem campos para tensão/corrente/perfil | `measurement`, `requested_current_limit_ma`, `advertised_current_limit_ma` | Extensão explícita do backend/UI; não enviar campos extras ao schema atual |

O backend atual, em `apps/api/app/schemas.py`, proíbe campos extras; admite estados físicos `idle/reserved/charging/stopped/fault`, ACKs `received/applied/failed` e fonte `simulated/measured/estimated`. O serviço em `apps/api/app/modules/devices/service.py` exige estado físico compatível para aceitar ACKs, energia não decrescente e energia final imutável. Não basta trocar a URL da API existente pela URL local.

**Presença exige cuidado:** TPS25810 com `EN=0` desliga também a detecção CC. `UFP#` alto nessa condição não prova que o cabo foi removido. O novo carregador deve informar `unknown`; saída desligada não implica `detached`. Em particular, o `connected=false` exigido pelo fluxo atual de `RELEASE` não pode ser fabricado a partir de `EN=0`. Essa incompatibilidade precisa ser resolvida antes da integração do painel; o contrato não a oculta.

## Perfis elétricos e o que cada número significa

- `requested_current_limit_ma`: perfil solicitado e aceito pelo dispositivo.
- `advertised_current_limit_ma`: perfil Type-C selecionado e conferido nos GPIOs de uma montagem previamente ensaiada. Não é leitura independente da tensão CC e não prova que o celular adotou o perfil. Vale `null` com a fonte desabilitada.
- `measurement.current_ma` e `power_w`: consumo efetivamente medido, incluindo sinal para detectar reverso. O celular decide quanto consumir dentro das condições de alimentação.

A proposta suporta somente perfis de **1.500 mA ou 3.000 mA, em 5 V nominais**, e somente quando cada perfil estiver liberado em `/v1/capabilities`. Isso não é um contrato USB-PD. Não existem nesta API `negotiated_limit_w`, seleção de 9/12 V, PWM de VBUS ou comando arbitrário de watts. Fonte, PCB, conectores, cabo e margem para o ESP32 precisam passar nos testes antes de liberar 3 A.

TPS25810 permite alterar a seleção de corrente anunciada. Isso, sozinho, não valida os transientes do conjunto nem garante redução imediata do consumo. A primeira implementação deve usar `limit_change_mode=stop_then_restart` após validar essa sequência em bancada: desabilitar, confirmar VBUS desligado, selecionar o novo perfil e habilitar novamente. `set_limit` exige `allow_interruption=true` nesse modo; caso contrário devolve `409 interruption_required`, sem alterar a saída. Durante a troca, a sessão e o contador continuam os mesmos e o lease continua correndo. Falha ao restabelecer a saída encerra a sessão e mantém o comando como `failed`.

`online_validated` fica reservado a uma revisão realmente ensaiada, com tempos de acomodação e resposta documentados. A alteração de perfil só recebe ACK após conferir os sinais e a condição de VBUS aplicável; esse ACK jamais confirma que o aparelho passou a consumir 7,5 ou 15 W.

## Execução, ACK e idempotência

1. O adaptador lê capacidades e estado, recebe `boot_id` e `revision`, e cria um UUID de comando. Campos desconhecidos são recusados.
2. O dispositivo autentica, valida o pedido e as capacidades, verifica sessão/lease e grava a aceitação antes de energizar ou mudar o perfil. Responde HTTP `202` com `status=received` e `verification=pending`.
3. A tarefa local executa o comando sem depender da conexão HTTP. O adaptador consulta `/v1/commands/{command_id}` até `applied` ou `failed`; uma resposta HTTP bem-sucedida não substitui isso.
4. Após ACK, o adaptador consulta `/v1/status` para obter o estado **atual**. Um START aplicado no passado pode ter sido seguido de STOP, falha ou reboot.

O `command_id` é a chave de idempotência, sem necessidade de um segundo cabeçalho. Mesmo ID com o mesmo conteúdo semântico retorna o registro existente (HTTP 200), sem executar de novo nem renovar prazos. O mesmo ID com conteúdo diferente retorna `409 idempotency_conflict`. Essa consulta ao registro vem antes das pré-condições de boot/revisão. Uma repetição de START nunca reinicia a energia da sessão.

Todo comando novo exige `expected_boot_id` atual. START e mudança de limite também exigem `expected_revision` atual; a aceitação reserva uma nova revisão. STOP e renovação não precisam de revisão, para que telemetria e mudanças normais não bloqueiem uma parada ou renovação válida. Mudanças autônomas de estado também incrementam a revisão. Só há uma sessão ativa; STOP tem prioridade e cancela um START/SET_LIMIT pendente, que termina com `superseded_by_stop`. A implementação precisa serializar essas transições.

Uma sessão encerrada não pode ser reiniciada com o mesmo UUID. Retenção persistente mínima de comandos e resumos: 24 horas, ampliável nas capacidades. Enquanto a sessão existir, seus comandos e identidade precisam continuar protegidos contra repetição. Pedido antigo cujo registro já expirou continua sujeito a boot, revisão e identidade da sessão; não se deve tratar 404 como autorização para reenviar START com identidade nova automaticamente. Na falta de espaço confiável para o registro, recusar nova energização com `503 storage_unavailable`. STOP válido e paradas autônomas devem desabilitar EN mesmo que a gravação falhe; a falha de registro não pode sustentar a carga. Nesse caso, um retorno 503 não garante que a saída tenha permanecido ligada ou que já esteja desligada: consultar o estado físico, sem inventar ACK persistido.

Critérios obrigatórios do executor futuro:

| Comando | Critério de `applied` |
| --- | --- |
| START | Seleção/EN conferidos, presença CC válida, sem FAULT e VBUS medido na faixa ensaiada, dentro do prazo de verificação |
| SET_LIMIT | Perfil selecionado conferido e sequência do modo de troca concluída; VBUS válido e presença válida ao concluir |
| STOP | EN desabilitado e VBUS medido abaixo do limiar de desligamento ensaiado; não basta escrever zero no GPIO |
| RENEW_LEASE | Sessão/boot/lease ainda válidos e prazo monotônico atualizado uma única vez; `verification=lease_updated` não é confirmação elétrica |

Os limiares de VBUS, prazo para conectar o celular, prazo de desligamento e idade máxima da amostra precisam ser estabelecidos pelos ensaios; não foram inventados aqui. Enquanto ausentes nas capacidades, START/SET_LIMIT não ficam operacionais. Celular deve estar plugado antes do START; ausência de detecção/VBUS até o prazo gera falha, desabilita a saída e não produz ACK fictício. Se a saída não puder ser confirmada desligada, informar `fault`, `output_state=unknown` e `verification=failed`, mantendo EN baixo.

## Autorização temporal e recuperação

START cria uma autorização temporária identificada por `lease_id`, com 15 s por padrão, faixa permitida de 5 a 30 s. O adaptador renova a cada 5 s usando UUID de comando novo. Apenas a primeira execução de uma renovação move o vencimento; repetir o mesmo comando não o move. GET, tráfego TCP, token correto, tela aberta ou leitura de telemetria não renovam o lease.

O relógio do lease é monotônico, local ao boot, sem depender de NTP. A aceitação do START inicia o prazo; a execução não pode energizar se esse prazo já expirou. Renovação aceita não ressuscita lease expirado. Nenhuma renovação ultrapassa `max_duration_s` contado do START. Expiração, limite de duração, sensor inválido, falha elétrica ou desconexão detectada iniciam parada local independentemente do painel. O adaptador só renova enquanto a autorização do backend continuar válida e suficientemente recente; não deve manter carga apenas porque a LAN está funcionando.

Reset, brownout ou watchdog devem colocar EN em baixo por hardware, antes da inicialização. Depois do boot, gerar `boot_id` novo, medir a saída, relatar a sessão anterior como interrompida (`device_reboot`) e nunca reexecutar START automaticamente. Resultados pendentes do boot anterior viram falha; resultados já terminais continuam como histórico. `boot_id` do resultado identifica a aceitação; `completed_boot_id` identifica o relógio usado em `completed_uptime_ms`, inclusive quando a falha é registrada no boot seguinte. O firmware só deixa `output_state=unknown` após verificar a condição da porta.

A eficácia desses prazos depende da implementação de tarefas, watchdog e circuito; nenhum tempo de corte foi medido neste trabalho. O resistor externo de estado desligado cobre reset/alta impedância, mas não prova corte em todo travamento possível. A fase de bancada deve testar CPU travada, Wi-Fi perdido, I²C travado e fonte retirada.

## Energia verdadeira e limitações de medição

O INA260 ficará depois de `OUT` do TPS25810 e antes do receptáculo USB-C, medindo energia na **porta do carregador**. Essa leitura exclui o ESP32, alimentação VCONN e perdas posteriores no cabo e no celular; não equivale à energia armazenada na bateria. É necessário definir os pontos de conexão de VBUS e corrente no esquema/PCB.

O registrador Power do INA260 é sempre positivo. Para preservar direção, ler Current como inteiro de 16 bits com sinal e calcular `power_w = voltage_v × current_ma / 1000`. Integrar a parcela positiva em Wh com tempo monotônico e amostras válidas durante a sessão; acumular a magnitude negativa em `reverse_energy_wh` separadamente. Não usar o módulo de corrente como energia entregue e não subtrair reverso de `energy_wh`.

Leituras ausentes ou vencidas geram grandezas `null`, qualidade inválida e parada; não viram zero nem uma estimativa baseada no perfil anunciado. Não interpolar sobre buracos além da idade máxima validada. A sessão registra `energy_quality=incomplete` e `unmeasured_ms`; um intervalo desconhecido por falta de alimentação torna a qualidade incompleta mesmo quando sua duração não puder ser determinada. `unmeasured_ms` é, portanto, o total conhecido, não prova de ausência de outros buracos.

Antes de publicar um valor de energia, a implementação precisa garantir que ele seja recuperável após reboot, ou preservar um máximo durável equivalente. O contador restaurado não pode regredir em relação ao último publicado ao backend. Isso exige definir a estratégia de gravação, frequência de publicação e desgaste da flash durante a implementação; ainda não foi resolvido em firmware. Interrupção de energia não permite inventar o consumo posterior ao último ponto seguro. Ao encerrar, congelar e persistir os totais; o adaptador mantém a reconciliação usando `/v1/sessions/{session_id}`. Para o backend atual, normalizar Wh a três casas com o mesmo arredondamento decimal documentado em `docs/esp32-protocol.md`.

## Exemplos e erros

Os pedidos completos estão em `openapi.json`, incluindo START a 1,5 A, troca para 3 A, STOP e renovação. O exemplo de 3 A só é elegível se `supported_current_limits_ma` contiver 3000. Exemplos de recusa:

| Pedido/situação | Resultado |
| --- | --- |
| `requested_current_limit_ma: 1000` | 422: perfil fora do contrato |
| Adicionar `requested_voltage_v: 9` ou `requested_power_w: 7.5` | 422: campo desconhecido |
| `lease_ttl_s: 31` | 422: prazo acima da faixa |
| Solicitar 3000 com capacidade liberada somente em 1500 | 422 `unsupported_current_limit` |
| Repetir UUID com outro perfil | 409 `idempotency_conflict` |
| START com `expected_boot_id` antigo | 409 `boot_mismatch`; ler estado, sem religar automaticamente |
| SET_LIMIT sem autorizar a interrupção exigida | 409 `interruption_required`; saída permanece no estado anterior |
| START sem ensaio do hardware | 503 `hardware_not_validated` |

Os schemas validam formato. Regras que dependem de estado (lease expirado, perfil liberado, revisão correta e confirmação física) exigem testes do executor futuro; não são demonstradas por um JSON válido.

## Rede do pitch

Usar Wi-Fi privado do grupo e token aleatório exclusivo do carregador, provisionado no adaptador. O token não deve ser uma credencial do cliente, a chave `Device` do backend ou o token de ownership. O exemplo HTTP pressupõe essa LAN; ele não cifra o tráfego e não deve ser exposto à Internet. Para ambiente compartilhado fora da demonstração, planejar transporte autenticado e cifrado antes de expandir o uso. Não habilitar CORS aberto nem registrar tokens em logs. O painel é o cliente local previsto; o celular do cliente continua falando com o backend existente.

## Fontes e verificação desta entrega

- Código lido: `firmware/esp32/src/{sensors,charging_controller,api_client}.cpp`, `apps/api/app/schemas.py`, `apps/api/app/modules/devices/{routes,service}.py`.
- Contratos existentes: `docs/api.md`, `docs/esp32-protocol.md` e `docs/plano-prototipo-usb.md`.
- [TI TPS25810 — datasheet](https://www.ti.com/lit/ds/symlink/tps25810.pdf): fonte Type-C, seleção de corrente, sinais e desabilitação.
- [TI INA260 — datasheet](https://www.ti.com/lit/ds/symlink/ina260.pdf): registradores, sinal de corrente e medição.

Foram verificados sintaxe JSON, referências locais, unicidade de operações, exemplos positivos e recusa estrutural de pedidos fora do contrato. Essa verificação não é teste de rede, de firmware ou da eletrônica. Antes de implementar a ligação ao painel, resolver a presença desconhecida, a persistência de energia e os tempos físicos da montagem final.
