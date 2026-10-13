# Tarifação por horário e ofertas transparentes

Planejamento de 1 de outubro de 2026. Esta frente propõe implementação futura; não altera código, banco, preços ou ambiente publicado. O MVP usa regras determinísticas e mantém a tarifa aceita até o fim da sessão. RFID e separação solar/rede permanecem fora do escopo.

## Base comprovada

O [modelo atual](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/models.py:64>) guarda `Connector.price_per_kwh` com quatro casas decimais. [START](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/service.py:52>) valida cupom e congela preço/desconto na sessão. A [telemetria](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/devices/service.py:221>) calcula estimativa usando esse snapshot. Não existem tabela horária, orçamento persistido ou preço condicionado à demanda.

O [planejador móvel](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/mobile/src/chargegrid_app/services/planning.py:5>) estima energia/custo pela potência nominal, antes de cupons. A [revisão anterior ao início](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/mobile/src/chargegrid_app/screens/charging.py:501>) consulta novamente condições e pede revisão se mudaram. Ainda falta um orçamento autoritativo que feche a diferença entre a leitura pelo app e a criação da sessão. Reservar não congela preço: o contrato atual reserva disponibilidade por dez minutos após confirmação.

## MVP: tarifa escolhida antes da recarga

Criar tabela por posto com dias da semana, horários locais e vigência. Começar com duas faixas publicadas, por exemplo R$ 1,20/kWh fora do pico e R$ 1,80/kWh no pico, mantendo preço-base como cobertura obrigatória. São valores de demonstração, não recomendação comercial.

O backend resolve a faixa ao emitir orçamento. A tarifa pode variar entre ofertas, mas cada sessão tem um preço fixo aceito. Se começar fora do pico e atravessar a mudança, conserva esse preço. Isso mantém compatibilidade com comando START, orçamento e cupom atuais. Cobrança segmentada a cada faixa exigiria outro contrato, medição por intervalo e aceite próprio; fica fora do MVP.

Tabela usa timezone IANA por posto, inicialmente `America/Sao_Paulo`; eventos e vigência persistem em UTC. Faixas são intervalos semiabertos: começo incluso, fim exclusivo. Faixa noturna atravessando meia-noite vira dois intervalos ligados na publicação. Rejeitar sobreposições e publicação sem cobertura; não escolher preço maior por desempate. Exceções de feriados/data e tarifas específicas por conector podem vir depois. Relógio do telefone nunca determina preço.

Publicar cria versão imutável com responsável, vigência e trilha de alteração. Edição cria nova versão, sem reescrever histórico. Desativar tabela devolve novas ofertas ao preço-base; sessões e pedidos aceitos mantêm seus termos. O proprietário só administra seus postos; motorista consulta preço vigente, próxima mudança e condições da própria oferta.

## Um orçamento para todos os canais

Reutilizar `charging_quotes` e `POST /charging-quotes` propostos em [pagamentos](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/planejamento-features/03-pagamentos.md>). Não criar outro orçamento no app, MCP ou carteira. O serviço de tarifação fornece a esse contrato:

| Grupo | Campos propostos |
|---|---|
| Identidade | `quote_id`, titular, posto/conector, `tariff_version_id`, `rule_id` |
| Preço | `price_per_kwh`, moeda BRL, timezone, motivo e instante da resolução |
| Desconto | cupom, versão/termos, `discount_percent`, preço líquido exato |
| Limites | duração, `max_cost`, potência máxima usada na projeção, teto em centavos |
| Validade | `issued_at`, `accept_by`, estado e hash dos termos |
| Evidência | origem simulada, energia/custo estimados, hipóteses e texto de aceite |

Proposta: orçamento disponível para aceite por até cinco minutos, limitado à validade restante do cupom. Essa janela pode atravessar mudança de faixa: a oferta informa expressamente que o preço mostrado será honrado se aceita no prazo. Nova versão publicada não invalida silenciosamente uma oferta válida. A API valida prazo e titular sob transação, preservando idempotência.

Ao aceitar e criar pedido, o orçamento fica consumido e seus termos congelam no pedido. `accept_by` deixa de ser prazo de pagamento: o pedido tem `funding_deadline` separado, alinhado ao checkout, e prazo de início condicionado à reserva/disponibilidade. Definir esses prazos junto à frente de pagamentos; o checkout recomendado admite expiração mínima de dez minutos, conforme [documentação oficial Asaas](https://docs.asaas.com/docs/asaas-checkout). Aceitar orçamento não renova reserva automaticamente.

Cupom válido no aceite fica incorporado ao pedido, mesmo se vencer durante checkout. Cupom expirado antes do aceite exige novo orçamento. Revogação excepcional de oferta aceita precisa de motivo, aviso e tratamento financeiro explícito; não reprecificar. Pagamento tardio ou ponto indisponível segue bloqueio/devolução da frente financeira. START usa `payment_order_id` ou orçamento aceito sem valor devido, nunca valor calculado pelo cliente. Repetição recupera o pedido/sessão original, sem consultar a faixa atual.

## Energia, desconto e teto financeiro

Conservar Decimal na API e tarifa representada por string decimal com quatro casas. Energia em Wh; estimativa bruta = `energy_wh / 1000 × preço × (100 − desconto) / 100`. Não arredondar cada leitura para centavos nem somar diferenças arredondadas. No acerto final, aplicar uma política canônica, proposta `ROUND_HALF_UP`, uma vez, convertendo para centavos. Todos os canais usam o mesmo resultado.

`max_cost` é teto líquido após cupom, incluindo somente energia neste MVP. No modo tempo, projetar pré-pagamento pela potência máxima autorizada × duração × preço líquido; é teto conservador, não promessa de energia ou total consumido. Cupom de 100% e preço zero geram `no_amount_due`, mantendo duração obrigatória. Não dividir por preço zero para estimar energia por orçamento.

Simulador/controlador precisam usar preço líquido congelado e potência variável ao interromper por orçamento. Precisão do firmware e atraso de parada podem produzir excesso: preservar energia e custo bruto calculado, mas valor cobrável não ultrapassa teto aceito. A fronteira financeira registra a diferença e o motivo, sem cobrança adicional. Não reduzir energia para esconder excesso.

Pausa por balanceamento preserva preço; duração continua contando conforme o plano de demanda. Menor potência altera ritmo e previsão, não reduz automaticamente kWh necessários. Taxa de ocupação/overstay precisa de termos separados, consentimento e orçamento próprios antes de entrar na cobrança; não embutir taxa nova numa sessão de energia já aceita.

## Evolução por condições de demanda

Depois do horário, permitir faixas de oferta baseadas em demanda agregada fresca, com regras publicadas, teto de preço e estabilidade. Registrar entrada, origem, versão, validade e motivo; sem dado válido, usar preço-base publicado para novas ofertas. Previsão pode sugerir melhor horário, mas não publicar preço nem garantir economia.

Evitar multiplicador a cada oscilação: usar janelas e histerese explicitadas na política. O algoritmo elétrico continua independente, sem dar prioridade automática a quem paga mais. A demonstração inicial deve usar tabela horária; precificação automática por IA e cobrança durante variação de carga ficam posteriores.

## Implementação, integrações e falhas

1. Propor módulo `modules/tariffs`, tabela de versões/faixas e resolvedor puro; migração aditiva preserva o preço atual como base. Expor consulta e prévia; publicação autorizada pelo dono.
2. Integrar resolvedor ao orçamento canônico e copiar snapshot para pedido/sessão. Revisar START, cupom, precisão do dispositivo e pagamento. Sessões históricas conservam preços atuais, sem inventar faixa anterior.
3. Atualizar descoberta/filtros/ordenação, resumo do ponto e revisão no Flet para preço vigente com instante e validade. Preço do mapa é referência; aceite acontece no orçamento. Evitar filtro SQL somente em `Connector.price_per_kwh` quando houver tabela ativa.
4. Mostrar histórico com preço aceito e motivo. Exportações recebem versão, cupom, custo estimado e final; carteira financia o mesmo teto. Chat OpenRouter configurável e MCP público autenticado chamam os mesmos serviços; IA não cria descontos, publica preços ou altera titular pelo texto.

Concorrência, timezone inválido, tabela sem cobertura ou orçamento adulterado devem produzir erro claro ou base publicada definida, sem inventar tarifa. Timeout de aceite exige recuperar pela chave idempotente antes de novo pedido. Indisponibilidade do provedor não transforma oferta em paga.

## Aceite e demonstração

Verificar futuramente: fronteira exata de horário; meia-noite; cupom vencendo; nova versão concorrente; orçamento válido atravessando faixa; aceite expirado; replay; tabela de outro proprietário; Decimal/centavos; desconto integral; orçamento e potência variável; checkout tardio; mapa/filtro e histórico coerentes. Este planejamento não executou testes.

Demo: oferecer preço fora do pico, aceitar, mostrar pedido congelado e iniciar simulador. Ao trocar a faixa, mostrar outra oferta com preço maior e a sessão original intacta. Alterar potência pelo balanceamento, manter tarifa, encerrar e comparar energia simulada, consumo líquido e restituição sandbox. A vantagem apresentada é transparência verificável do preço aceito em todos os canais.
