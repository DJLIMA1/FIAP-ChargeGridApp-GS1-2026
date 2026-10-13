# Notificações, fila de liberação e overstay

Planejamento de 01/10/2026. Propõe implementação futura; não envia mensagens, altera código, cria tabelas ou efetua cobranças. RFID e separação solar/rede ficam fora.

## Base existente e diferencial

O [app](../../apps/mobile/src/chargegrid_app/app.py) atualiza a tela aberta por polling, suspende consultas durante ações e identifica dados antigos. [Recarga](../../apps/mobile/src/chargegrid_app/screens/charging.py) e [reserva](../../apps/mobile/src/chargegrid_app/screens/reservations.py) consultam a API a cada cinco segundos. Não existe inbox persistente, fila de espera ou entrega de notificações fora dessa experiência.

[Reservas](../../apps/api/app/modules/reservations/service.py) já possuem confirmação pelo dispositivo, prazo de dez minutos e cancelamento por RELEASE. [Disponibilidade](../../apps/api/app/service.py) exige equipamento online, reconciliado, sem sessão/reserva ativa, estado idle/stopped e `connected=false`. Prazo vencido não torna o ponto livre. [Sincronização](../../apps/api/app/modules/devices/service.py) confirma fim independentemente da disponibilidade. [Eventos de sessão](../../apps/api/app/session_events.py) registram fatos, com chaves únicas; aproveitá-los sem criar outra máquina de recarga.

O diferencial proposto é avisar sobre fatos verificáveis e oferecer oportunidade justa a quem espera. “Recarga encerrada” e “ponto liberado” precisam ser mensagens distintas.

## MVP de notificações

Criar inbox autenticada com data, tipo, título, texto determinístico, origem, recurso relacionado, validade e estado lido. Começar com fim confirmado, prazo de reserva encerrado, liberação confirmada, oferta da fila e alerta de permanência. Expiração temporal pode avisar “prazo encerrado, liberação pendente”; somente confirmação da máquina atual autoriza “reserva expirada e liberada”. START/STOP solicitado nunca gera mensagem de operação concluída.

Polling incremental por cursor, inicialmente dez segundos com app autenticado ativo e cinco na tela de fila, integrado ao mecanismo atual. Evitar um segundo temporizador concorrente por tela; um coordenador compõe atualizações e conserva proteção das ações. Ao retomar app/login, buscar itens persistidos. App fechado não recebe promessa de alerta imediato neste MVP. Falha de rede conserva mensagens e validade conhecida, exibindo atualização pendente; não executa ações offline em replay automático.

Preferências separadas por categoria; lembretes podem ser desativados sem apagar o fato do histórico. Entrar na fila pressupõe aceite dos avisos de oferta na inbox. Push nativo/Web Push fica para outra fase após verificar alvos, versão Flet, permissões, bibliotecas e entrega em segundo plano; este plano não presume suporte nem escolhe provedor. Nunca enviar WhatsApp, email ou SMS nesta rodada.

## Fila e oferta exclusiva

Primeiro escopo: fila por ponto, uma inscrição ativa por conta no aplicativo, entrada voluntária e saída a qualquer momento. Quem já possui sessão/reserva ativa fica inelegível; aceitar uma oferta exige nova validação. Ordem FIFO pelo timestamp do servidor, desempate estável por ID; cancelamento ou oferta perdida exige reentrada explícita no fim. TTL proposto de duas horas por inscrição, configurável e visível. Não exigir pagamento para obter posição nem permitir prioridade escolhida pela IA.

Quando `availability()` indicar livre com evidência recente, escolher o primeiro elegível sob lock do ponto. Criar oferta exclusiva de 120 segundos, proposta de produto ajustável, com prazo absoluto UTC. Durante esse prazo, o serviço central de admissão bloqueia reserva/START por outras contas, inclusive acesso por MCP; a UI mostra “oportunidade em confirmação”. A oferta guarda exclusividade de aquisição, sem fingir reserva física ou substituir estados do dispositivo. Exibir disponibilidade física e possibilidade de reservar separadamente.

Aceitar exige titular, token de oferta, validade e ponto novamente disponível. Na mesma transação, converter a oferta em chamada ao serviço de reserva existente e remover a exclusividade virtual: RESERVE continua pendente até ACK, depois começa o prazo vigente de dez minutos. A oferta não inicia recarga, não dispensa presença e não renova reserva automaticamente. Essa conversão deriva de inscrição e aceitação explícitas, não de uma previsão de horário.

Adotar ordem de locks compatível com o código: perfil, ponto e oferta. Executor identifica candidato sem lock, adquire nessa ordem e revalida a cabeça da fila; se mudou, libera e repete. Nunca toma depois um perfil sob lock já adquirido do ponto. Unicidade no banco impede duas ofertas ativas ou duas conversões. Se duas aceitações concorrerem, somente uma ganha; a outra recebe resultado idempotente ou conflito verificável.

Oferta recusada/expirada/cancelada libera somente o bloqueio virtual e passa ao próximo após revalidar a máquina física. Após criação de reserva, seguir sua máquina e esperar RELEASE confirmado antes de nova oferta. Ponto offline/fault/reconciling durante oferta invalida a oportunidade; avisar sem prometer outro ponto. Inscrição mantém espera original nesse caso de falha técnica; falha de confirmação comprovadamente técnica também pode devolver essa inscrição à espera, sem gerar nova reserva silenciosa.

## Conexão, ocupação e overstay

Há um gap de simulação: [STOP no firmware](../../firmware/esp32/src/charging_controller.cpp) e [simulador Python](../../tools/device_simulator.py) fazem `connected=false`; [sensores](../../firmware/esp32/src/sensors.cpp) vinculam conexão ao estado charging. Hoje isso não demonstra veículo conectado após terminar.

Alinhar com o plano 01 um estado de conexão simulada independente de energia/potência: cenários “desconectar ao terminar” e “continuar conectado até ação simulada”. STOP zera potência e confirma fim; desconexão é outro fato. Dispositivo legado continua com capacidades existentes, sem inventar observação adicional. Anunciar capacidade/origem de detecção e persistir conexão coerente no reboot. `connected` representa cabo/conexão, não prova uma vaga de estacionamento desocupada. Sem sensor específico, usar “ponto desconectado”, evitando alegar controle de ocupação real.

Overstay exige fim terminal confirmado da sessão e ocupação/conexão confirmada, vinculada à mesma permanência. Registrar início conservador pelo recebimento de evidência válida, sem retroagir por estimativa do relógio. Tolerância inicial proposta de cinco minutos, exposta no início; primeiro MVP gera alerta ao motorista e indicador ao operador, com cobrança zero.

Pausa por balanceamento preserva sessão ativa, conexão e estado charging: potência zero não inicia overstay. Offline, sequência repetida, reboot, ausência de sensor ou vínculo incerto suspendem observação e marcam intervalo desconhecido. Não somar intervalo desconhecido a duração confirmada. Nova evidência inicia/retoma observação identificada, sem reconstruir ocupação intermediária. Desconexão encerra o intervalo; sua confirmação habilita a disponibilidade somente se as demais condições atuais também valerem.

Cobrança futura depende de política versionada aceita antes de iniciar, preço/teto/tolerância transparentes, identificação confiável de ocupação e acerto financeiro auditável. Não adicionar custo ao teto pré-pago de energia silenciosamente. Sem prova suficiente, não cobrar; operador não pode converter alerta em dívida arbitrária. O MVP financeiro do plano 03 permanece separado.

## Contratos e processamento propostos

Propor módulo `apps/api/app/modules/notifications/` para inbox/preferências e `modules/waitlists/` para admissão/fila. Flet ganha `screens/notifications.py`, badge no cabeçalho e painel de espera em postos; cadastro de rotas reutiliza navegação atual. Alembic futura cria:

- `notification_inbox`: titular, evento deduplicado, tipo, conteúdo/versionamento, criado/lido e alvo seguro.
- `notification_outbox`: trabalho persistente, chave, prazo, lease, tentativas e resultado.
- `waitlist_entries`/`queue_offers`: posição estável, elegibilidade, estado, expiração e vínculo com reserva.
- `occupancy_intervals`: sessão/ponto, origem, evidências inicial/final, observação conhecida/desconhecida e política de tolerância.

Endpoints propostos: `GET /v1/notifications?cursor=...`, `POST /v1/notifications/{id}/read`, `PATCH /v1/notification-preferences`, `POST /v1/waitlist-entries`, consulta/cancelamento da própria inscrição e `POST /v1/queue-offers/{id}/accept`. Campos mínimos incluem `event_id`, `kind`, `observed_at`, `received_at`, `source`, `expires_at`, `session_id/reservation_id/connector_id` quando pertinentes. Prazos usam servidor; app apresenta fuso local.

Gravar fatos e outbox na mesma transação de sync/reserva; processamento só fica visível após commit. O [ambiente atual](../../apps/api/vercel.json) limita função a 30 segundos e possui apenas keepalive diário: implementar executor durável/agendador com lotes curtos, leases e retentativas. Polling pode reconciliar prazos idempotentemente; tarefas em memória não garantem expiração sem cliente aberto. Deduplicar por recurso + evento + destinatário; não repetir alerta a cada sync. Ordenar pelo domínio, sem inferir que ordem de entrega prova ordem física.

## Segurança, etapas e aceite

Titular consulta apenas sua inbox/fila; operador vê agregados e permanências dos próprios pontos, sem divulgar posição nominal de terceiros. Conteúdo externo futuro deve ser mínimo; nenhuma credencial, #F, chave privada ou dados bancários. MCP autentica a conta e chama os mesmos serviços; modelo gratuito OpenRouter substituível não decide prioridade, liberação ou cobrança.

Etapas: inbox/eventos e polling; fila/admissão com oferta atômica; conexão independente no simulador e overstay sem cobrança; depois entrega externa e eventual contrato financeiro. Dependências: eventos de sessão, disponibilidade/reconciliação, plano 01 e executor durável. Gestão de demanda informa pausas; suporte recebe falhas sem transformar alerta em chamado automaticamente.

Aceites futuros: evento duplicado gera uma mensagem; STOP pendente não libera oferta; fim conectado avisa fim e mantém indisponibilidade; pausa não gera overstay; expiração virtual não cria RELEASE; reserva segue dez minutos desde confirmação; duas aceitações não duplicam reserva; offline não acumula cobrança; logout não mostra inbox da conta anterior; retorno mostra aviso perdido e prazo atualizado. Nenhum teste foi executado nesta rodada documental.

Demo: duas contas entram na fila; sessão termina ainda conectada; motorista recebe aviso e operador vê alerta de tolerância, sem cobrança. Após desconexão simulada confirmada, primeira conta recebe oferta; deixar vencer, oferecer à segunda e aceitar. Mostrar RESERVE pendente, ACK e prazo de chegada; perder rede antes da liberação e demonstrar ausência de oferta falsa.
