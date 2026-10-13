# Carteira e saldo para recargas

Planejamento de 1 de outubro de 2026. Carteira é uma fase opcional posterior ao pagamento avulso de [03-pagamentos](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/planejamento-features/03-pagamentos.md>). Este documento não implementa movimentação, banco ou integração. RFID e separação solar/rede permanecem excluídos.

## Base comprovada e objetivo

Não existe carteira, saldo, recarga de crédito ou livro de lançamentos em [models.py](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/models.py>). `ChargingSession` guarda preço, cupom, teto e `cost_estimate`; isso não comprova recebimento. [start](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/service.py>) congela tarifa/desconto e emite START idempotente, sem autorização financeira. [security.py](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/security.py>) autentica o titular; [service.py](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/service.py>) usa bloqueios de usuário/ponto e chave com hash do corpo. Preservar esses mecanismos.

O diferencial é permitir reservar orçamento de um saldo já disponível, mostrar consumo e devolver a sobra ao próprio saldo, com trilha verificável. Começar com **crédito de demonstração**. Pagamento avulso continua funcionando sem carteira; saldo não é pré-requisito do MVP. Não incluir transferência entre pessoas, saque ou conversão de bônus em Pix. Produção fica para decisão posterior sobre operação, recebedor, condições comerciais e avaliação específica; o plano não presume que um saldo interno seja produto financeiro autorizado.

## Separar origens e ambientes

| Bolsão proposto | Origem | Apresentação |
|---|---|---|
| `demo_credit` | Concessão única autorizada de demonstração | “Crédito de demonstração — sem valor financeiro” |
| `provider_sandbox` | Recebimento fictício conciliado | “Saldo de testes — sandbox” |
| `provider_live` | Recebimento real conciliado, fase futura | Saldo em BRL com extrato e referência do recebimento |

Cada bolsão tem titular, moeda, ambiente e recebedor identificados. Não somar testes a dinheiro real nem usar saldo global da conta do provedor como saldo de um consumidor. A documentação do Asaas confirma que sandbox tem ambiente/chaves próprios e não movimenta valores reais; seus recursos também podem diferir da produção. [FAQ oficial](https://docs.asaas.com/docs/faq-sandbox-1).

No primeiro fluxo, escolher **um bolsão por sessão**, sem pagamento misto ou completar saldo automaticamente. Um crédito demo só financia jornada explicitamente demonstrativa. Origem da energia continua independente: uma sessão pode ter `measurement_source=simulated` e financiamento sandbox; pagamento não transforma simulação em medição. Bônus comerciais futuros exigiriam bolsão/política próprios, sem chamar esse benefício de saldo pago.

## Ledger, autorização e acerto

Guardar valores monetários em centavos inteiros, nunca float. Livro de lançamentos imutável, com transações e partidas balanceadas entre contas de disponível, reservado, consumo e contrapartida da origem. Cada evento possui referência de negócio, ambiente, sequência, data UTC, autor e chave única; correção gera lançamento reverso vinculado ao original, sem editar/apagar histórico. Saldo materializado é projeção reconstruível e atualizada na mesma transação do livro.

Estados de autorização propostos: `held`, `attached_to_session`, `awaiting_final_measurement`, `settled`, `released`, `review_required`. Esses estados não substituem estados físicos nem estados do gateway.

1. API cria o mesmo orçamento autoritativo da frente de pagamentos. Consumidor confirma ponto, tarifa/cupom, teto, validade e bolsão; API reserva integralmente o teto. Disponível diminui; reservado aumenta. Falta de saldo bloqueia a autorização, oferecendo pagamento avulso.
2. START revalida orçamento, titular, presença, ponto e autorização não consumida. Associar sessão, hold e emissão do comando na mesma transação de banco. Autorização só pode financiar uma sessão; o dispositivo recebe limites, sem acesso ao saldo ou gateway.
3. Durante recarga, custo continua estimado. Não debitar a cada telemetria: isso multiplica arredondamentos e replays. Mostrar o consumo estimado contra o teto reservado.
4. Com término e medição final validados, o acerto canônico calcula custo em centavos, limitado ao teto. Parte reservada vira consumo; sobra volta ao disponível do **mesmo bolsão**. Um acerto por sessão/versão, com lançamento único.

Exemplo demo: crédito R$ 50; autorização de R$ 20 deixa R$ 30 disponíveis e R$ 20 reservados. Consumo final de R$ 12 libera R$ 8: saldo final disponível R$ 38, reservado zero e consumo R$ 12. Isso é liberação de reserva interna, **não estorno Pix**. Estorno de uma recarga de saldo via gateway seria outro processo, vinculado à cobrança original e separado do acerto da sessão.

Hold sem sessão pode expirar após comprovar que nenhuma associação/START ocorreu. Hold associado não expira por relógio durante falha de comunicação. STOP pendente, reboot ou ausência de ACK mantêm reserva e `awaiting_final_measurement`; não presumir parada ou cobrar energia extrapolada. Reutilizar revisão/prazos da frente 03: sem evidência suficiente, encaminhar decisão auditável; dados tardios não autorizam débito silencioso depois de acerto definitivo.

## Concorrência e proteção do saldo

Bloquear as contas afetadas com `SELECT … FOR UPDATE`, revalidar saldo sob bloqueio e gravar hold/partidas/projeção/idempotência atomicamente. Disponível e reservado têm restrições de não negatividade. A documentação do PostgreSQL explica que bloqueios de linha duram até o fim da transação e recomenda ordem consistente para evitar deadlocks. [Bloqueios explícitos](https://www.postgresql.org/docs/current/explicit-locking.html).

START preserva a ordem atual de usuário/ponto antes de bloquear carteira. Nenhum worker pode segurar carteira e depois adquirir ponto; quando precisar de ambos, deve seguir a ordem comum definida para os módulos. Não manter transação aberta aguardando provedor, usuário ou dispositivo. Conflitos transitórios exigem retry limitado da transação inteira, com a mesma chave.

Restrições únicas cobrem concessão demo por usuário/campanha, crédito por recebimento do provedor/ambiente, autorização por orçamento e consumo por acerto. Uma chave com corpo diferente gera conflito. Timeout após commit recupera o mesmo recurso; rollback não deixa hold órfão. Conciliação compara ledger/projeção/holds e recebimentos, congelando novas operações do bolsão em divergência, sem editar saldo para “bater”.

Contestação de recarga congela a parcela ainda disponível e abre revisão. Se já houve consumo, registrar exposição/pendência separada e impedir novas autorizações afetadas; não tornar o disponível negativo, apagar consumo histórico ou compensar de outro bolsão automaticamente. Produção exige homologar essa política antes de ativar recargas reais.

## Contratos e módulos propostos

Todos os recursos abaixo são novos, não endpoints existentes:

| Contrato | Responsabilidade |
|---|---|
| `GET /v1/me/wallets` | Disponível, reservado, origem, ambiente e estado por bolsão |
| `GET /v1/me/wallet-entries` | Extrato paginado, filtro por período/origem e referências |
| `POST /v1/wallet-authorizations` | Aceitar `quote_id` e `wallet_id`, reservar teto idempotentemente |
| `POST /v1/wallet-authorizations/{id}/cancel` | Solicitar cancelamento; liberar somente quando elegível |
| `POST /v1/wallet-topups` | Fase posterior: pedido hospedado de recarga com gateway |

Titular deriva da autenticação, nunca do corpo. Operador vê apenas lançamentos ligados às sessões dos seus postos, não toda carteira do consumidor. O app apresenta saldo/hold/consumo separados; em timeout consulta autorização existente antes de tentar novamente.

Criar futuramente `modules/wallet/{routes,service,ledger}.py`, schemas e migração aditiva para `wallet_accounts`, `wallet_transactions`, `wallet_entries`, `wallet_authorizations` e `wallet_topups`. Flet ganha `screens/wallet.py`; confirmação de recarga oferece escolha de financiamento. Sessões antigas não recebem lançamentos fictícios.

Generalizar o contrato financeiro para referência tipada `funding={kind: payment_order|wallet_hold, id: ...}` mantendo pagamento avulso. Reutilizar orçamento, elegibilidade e acerto; hold não cria `payment_order=confirmed` nem evento falso de gateway. Não implementar dois cálculos de preço.

## Sequência, dependências e aceite

**Fase 1:** ledger e crédito demo concedido uma vez, extrato, hold, START e acerto simulado. **Fase 2:** recarga sandbox depois de inbox/outbox/conciliação estáveis. Crédito nasce de recebimento conciliado, não de retorno do checkout ou mera confirmação de cartão; eventos repetidos creditam uma vez. **Fase 3:** avaliar produção e homologar restituições/contestações, mantendo ambientes isolados.

Tarifação fornece snapshot e arredondamento; simulador fornece evidência final. Exportações distinguem aporte, reserva, consumo e liberação, sem contar todos como receita. MCP compartilhado do chat OpenRouter começa com consulta de saldo/extrato. Autorização futura gera resumo e ação de confirmação humana vinculada ao orçamento; não oferecer `set_balance`, concessão livre, marcar pago ou débito arbitrário. Chaves do provedor permanecem no backend.

Aceites planejados: duas autorizações concorrentes de R$ 20 com saldo R$ 30 aprovam apenas uma; replay não duplica crédito/hold/acerto; titular alheio é negado; cupom/teto persistem; queda mantém valor reservado; reversão preserva histórico; reconstrução reproduz saldo; sandbox não aparece como produção. Demo apresenta R$ 50 → hold R$ 20 → consumo R$ 12 → liberação R$ 8, com extrato auditável. Estes testes são critérios futuros; nenhum foi executado nesta rodada de planejamento.
