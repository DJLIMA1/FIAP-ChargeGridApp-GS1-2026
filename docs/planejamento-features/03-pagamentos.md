# Pagamentos e conciliação de sessões

Planejamento de 1 de outubro de 2026. Proposta para implementação futura; nenhum pagamento, cadastro, migração ou publicação foi executado. RFID e separação solar/rede estão fora. Carteira não é dependência.

## Base existente

O modelo [ChargingSession](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/models.py:121>) guarda `max_cost`, tarifa, desconto, energia, origem e `cost_estimate`, sem cobrança ou liquidação. O serviço [start](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/service.py:52>) valida presença/reserva/cupom e congela tarifa/desconto, emitindo START com limites. A [sincronização](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/devices/service.py:183>) exige ACK compatível para confirmar início, calcula custo por telemetria e trata reboot com STOP. O [resumo do operador](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/routes.py:121>) soma estimativas, sem representar dinheiro recebido.

Precisamos acrescentar o domínio financeiro preservando essas garantias e as alterações locais. Pagamento confirmado não comprova início, parada, energia entregue ou vaga liberada.

## Escolha fundamentada do provedor

Recomendo **Asaas Checkout em sandbox**, pagamento avulso hospedado com Pix/cartão. O fluxo documentado cria checkout, retorna link e acompanha eventos; redirecionamento de sucesso não comprova pagamento. A expiração mínima é dez minutos. Isso reduz a interface própria e evita receber número/CVV no Flet ou na API. É recomendação técnica para testes, não contratação. [Asaas Checkout](https://docs.asaas.com/docs/asaas-checkout).

O sandbox separa contas, chaves e saldo fictício da produção e permite testar cobranças, cartões e webhooks. Para confirmar recebimentos fictícios de determinadas cobranças Pix, a documentação orienta usar a interface sandbox; não promete endpoint genérico de confirmação. Homologar especificamente o checkout escolhido e sua ligação às cobranças antes da demo. [Sandbox](https://docs.asaas.com/docs/sandbox-1), [FAQ sandbox](https://docs.asaas.com/docs/faq-sandbox-1).

**Alternativa: Mercado Pago Checkout Pro**, também hospedado, com cartões de teste. Na documentação desse produto, o teste de Pix termina pendente; portanto, não assumir que teremos aprovação Pix completa igual ao cartão. Outro produto/API exigiria homologação própria. Conta, aplicação e credenciais continuam necessárias. [Testes do Checkout Pro](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/integration-test/test-purchases).

Disponibilidade efetiva, limites, cadastro/aprovação e condições comerciais dependem da conta; não foram verificados. Um adaptador `PaymentGateway` com `create_checkout`, `get_payment`, `refund` e normalização de eventos permite trocar provedor sem duplicar regras. SDK é opcional; começar com cliente HTTP existente. Produção com vários vendedores exigirá definir recebedor, repasses e contratos; sandbox usa um recebedor de demonstração, sem simular repasse como realizado.

## MVP: teto pré-pago por sessão

1. API cria orçamento com tarifa aceita, cupom validado, duração, origem simulada e teto em centavos. Se existir `max_cost`, ele é o teto; no modo tempo, derivar teto conservador da potência máxima, duração e preço aceito, exibindo-o antes de confirmar. Cupom de 100% produz `no_amount_due`, sem inventar pagamento.
2. Consumidor confirma explicitamente teto e regra de devolução; API cria pedido e checkout. Reserva continua com seus prazos atuais. Como checkout dura ao menos dez minutos, expiração e disponibilidade precisam aparecer na interface; pagar não prolonga reserva automaticamente.
3. Evento financeiro autenticado, vinculado ao pedido, confirma o pré-pagamento. Ao voltar, app consulta API. Antes de START, revalidar presença atual, ponto, reserva e funding. Consumir o pedido uma única vez e usar seu snapshot, sem reler preço aumentado.
4. Se pagamento chegar após prazo ou ponto ficar indisponível, bloquear início e devolver integralmente; não redirecionar automaticamente para outro ponto.
5. Após encerramento e medição final validada, calcular valor consumido, limitado ao teto, e devolver diferença ao mesmo meio. Exemplo sandbox: pré-pago R$ 20, consumo simulado R$ 12, estorno R$ 8. Excesso por atraso de parada não autoriza cobrança adicional silenciosa.

Escolher pré-pagamento uniforme evita duas máquinas de negócio no primeiro MVP. Pré-autorização/captura de cartão pode vir depois, condicionada ao produto e validade da autorização; Pix não deve ser tratado como reserva de limite de cartão.

O Asaas documenta estornos integrais/parciais Pix/cartão e avisa que taxas não são devolvidas, podendo faltar saldo para restituição integral. Portanto, registrar `refund_due` separado de `refunded`, provisionar saldo fictício para homologação e não prometer estorno concluído na solicitação. [Estornar cobrança](https://docs.asaas.com/reference/estornar-cobranca).

## Estados e conciliação independente

| Domínio | Estados propostos |
|---|---|
| Recarga | Preservar `starting`, `charging`, `stopping`, terminal atual |
| Pagamento | `pending`, `confirmed`, `received`, `failed`, `expired`, `disputed` |
| Acerto da sessão | `awaiting_final_measurement`, `review_required`, `finalized` |
| Estorno | `due`, `submitted`, `completed`, `failed`, `unknown` |

Separar confirmação de pagamento e disponibilização do saldo: no cartão, os momentos podem diferir. Guardar também estado bruto do provedor e valores pagos/estornados; um campo booleano `paid` é insuficiente.

Sem contato, com STOP pendente ou após reboot, manter `awaiting_final_measurement`; não extrapolar energia pelo relógio para cobrar. Aceitar evidência final consistente com sessão, `boot_id`, sequência e origem, respeitando energia monotônica e imutabilidade terminal atuais. Sem evidência final após quinze minutos, encaminhar revisão, mostrando prazo e responsável. Política proposta: revisão até 24 horas e, sem prova suficiente, devolução integral autorizada pelo operador; dados tardios não geram nova cobrança automática. Esse prazo é decisão de produto para homologar, não regra do provedor.

Falha de START só permite estorno automático integral quando há comprovação de ausência de consumo e parada reconciliada; em estado incerto, seguir revisão. Duplicação comprovada de pagamento gera devolução da cobrança excedente sem financiar outra sessão. Contestação abre pendência auditável; não apaga sessão nem saldo histórico.

## Contratos e persistência propostos

Endpoints novos, sujeitos ao padrão de versionamento do projeto:

| Endpoint | Responsabilidade |
|---|---|
| `POST /charging-quotes` | Orçamento autoritativo, snapshot, teto, validade |
| `POST /payment-orders` | Aceitar orçamento e criar checkout idempotente |
| `GET /payment-orders/{id}` | Consultar somente titular/operador autorizado |
| `POST /webhooks/payments/asaas` | Receber evento autenticado do provedor |
| `POST /payment-orders/{id}/cancel` | Cancelar intenção; restituição segue conciliação |

START recebe `payment_order_id`; requer pedido confirmado, válido, compatível e não consumido. Respostas incluem `amount_cents`, `currency=BRL`, `payment_environment=sandbox`, `measurement_source=simulated`, `checkout_url`, estado financeiro, consumo estimado/final, devolução devida/concluída e referências auditáveis. Nunca aceitar valor final calculado pelo aplicativo ou pela IA.

Migração Alembic futura, aditiva: `charging_quotes` (snapshot/versionamento/validade), `payment_orders` (titular, recebedor, orçamento, vínculo único com sessão), `payment_attempts` (provedor/ambiente/IDs/valor/estado), `payment_webhook_inbox` (evento único/hash/processamento), `payment_refunds` e `payment_outbox`. Valores monetários em centavos; energia/tarifa permanecem Decimal com arredondamento final definido. Restrições impedem consumo duplo, estorno acima do pago e IDs repetidos por provedor/ambiente. Sessões históricas ficam `legacy_unbilled`, sem backfill que declare pagamento.

Webhook valida HTTPS e `asaas-access-token` em tempo constante, limita corpo e confere IDs/valor/ambiente. Esse token compartilhado é o mecanismo documentado; não inventar assinatura HMAC do provedor. Persistir inbox antes de 2xx, deduplicar pelo ID e reconciliar eventos fora de ordem consultando recurso quando necessário. Segredos e dados de cartão ficam fora de logs, exports e MCP. [Webhook](https://docs.asaas.com/docs/criar-novo-webhook-pela-api), [Eventos de checkout](https://docs.asaas.com/docs/checkout-events).

No serverless, inbox/outbox têm processamento durável com leases, tentativas e execução agendada; tarefas em memória após resposta são insuficientes. O cron atual de keepalive não oferece isso. Timeout do provedor vira `unknown`: consultar IDs/referência ou encaminhar revisão antes de repetir criação/estorno. `externalReference` correlaciona, sem assumir deduplicação automática. [Retries e idempotência](https://docs.asaas.com/docs/retries-e-idempot%C3%AAncia).

## Etapas, dependências e aceite

Implementar primeiro contratos, migração local e adaptador determinístico explicitamente `mock`; depois sandbox, webhook/inbox/outbox e restituição; finalmente Flet, relatórios e demonstração. Testes locais não precisam de credenciais. Sem gateway disponível, mostrar pendência/indisponibilidade; nunca converter mock em pago real.

Tarifação fornece snapshot aceito e total canônico; simulador fornece término/evidência final. Carteira futura usa o mesmo pedido e acerto, sem misturar fontes ou reembolsar saldo interno como Pix. Exportação diferencia estimativa, pré-pagamento, consumo, estorno, taxa e margem; receita bruta/comissão não são lucro. MCP reutiliza serviços para consultar e solicitar checkout mediante confirmação explícita, sem ferramenta livre para marcar pago ou enviar restituições.

Aceites: duas solicitações iguais produzem um pedido; webhook duplicado não duplica saldo/START/estorno; retorno falso não confirma pagamento; pedido alheio é negado; Pix pendente não inicia; pagamento tardio não inicia; reboot conserva evidência e pendência; ausência de medição não liquida estimativa; centavos/cupom/teto permanecem consistentes; falha de estorno continua visível até conciliar.

Demo: checkout sandbox → confirmação do provedor → START/ACK → energia simulada → perda/retorno → término validado → estorno parcial confirmado. Entregar recibo financeiro identificado como teste separado do resumo de energia simulada. Bloqueios externos futuros: conta sandbox, habilitações e credenciais, URL HTTPS e agendador durável. O planejamento não depende deles.
