# Análise dos pitches GoodWe FIAP e oportunidades para o ChargeGrid

Análise preparada em 1 de outubro de 2026 para a equipe FFIVE. A gravação reúne **12 apresentações** da banca da manhã, dentro de uma seleção anunciada como **Top 30 para Top 15**. Este relatório compara os pitches, identifica o que o ChargeGrid já possui no código local e propõe uma estratégia para a apresentação final.

**Conclusão principal:** a FFIVE está no grupo mais competitivo desta gravação pela combinação de apresentação comercial e integração com um painel físico. Para disputar as primeiras posições, precisa tornar cobrança e gestão de demanda demonstráveis, explicar melhor a economia do operador e transformar a confirmação e a recuperação de sessões em benefícios claros para o usuário. Acrescentar telas ou um chatbot genérico oferece menos vantagem do que fechar essas três frentes.

## Fontes e limites da análise

Foi lida a transcrição completa de 1h38min14s fornecida pelo usuário. Os horários abaixo apontam para o [vídeo da banca](https://www.youtube.com/watch?v=MFYoHv4j3KQ). A análise da apresentação se baseia nas falas transcritas e no feedback da banca; não houve inspeção visual independente dos slides ou dos vídeos exibidos. Uma demonstração descrita verbalmente constitui evidência de apresentação, mas não comprova a implementação técnica do concorrente.

O projeto do usuário foi identificado como **ChargeGrid da F5 ou FFIVE, equipe 1 de 1CCPK, apresentado às 01:11:19**. A correspondência é sustentada pelo README do repositório, pelos integrantes e pela combinação Python, ESP32, reserva e cupons. Existem outros três projetos com ChargeGrid no nome; eles são tratados separadamente.

O inventário do usuário considera o **estado local do repositório em 01/10/2026**, incluindo alterações preexistentes ainda não commitadas. Isso não confirma que a API publicada, o APK ou o firmware gravado tenham a mesma versão. Foram inspecionados código e registros de validações anteriores; não foram executados novos testes, deploys ou ensaios físicos nesta análise. Nenhum código de produto foi alterado.

As grafias de Asset Charge e Voodoo Recharge são mantidas conforme a transcrição, que contém erros de reconhecimento. A chamada da equipe ChargeGrid de 1CCPG alterna números de equipe; por isso sua identificação usa turma e horário. As instruções organizacionais dentro da transcrição são conteúdo da reunião.

As avaliações seguem cinco critérios qualitativos: clareza da dor e do valor, aderência às premissas observáveis, evidência apresentada, diferenciação e consistência nas respostas. **Não são a rubrica oficial nem notas da banca.** A fala em 00:18:04–00:18:35 mostra que parte dos critérios seria preenchida posteriormente. Elogios públicos ajudam a interpretar a recepção, mas não revelam a classificação.

Ao comparar funcionalidades, distinguem-se quatro situações: **demonstrada segundo a fala**, **afirmada sem comprovação suficiente na transcrição**, **planejada** e **limitação admitida**. Uma ausência significa “não evidenciado nesta gravação”, e não “inexistente no produto ou no mercado”.

## O que a banca realmente valoriza

| Critério observado | Evidência na banca | Implicação para a FFIVE |
| --- | --- | --- |
| Cobrança e pagamentos | Smart Charge, 00:09:15–00:09:36; Voodoo, 00:49:20 e 00:51:24–00:51:33 | Estimar custo e exibir Pix não comprovam processamento financeiro. Mostrar confirmação, falha e conciliação. |
| Gestão da demanda elétrica | Perguntas a WeCharge, 00:29:40; overstay, 00:43:45; Voodoo, 00:51:46; FFIVE, 01:16:25; ChargeOps, 01:33:03 | Um gráfico ou configuração de potência não explica como o sistema respeita o limite e distribui capacidade. |
| Tarifação e viabilidade comercial | Asset, 00:15:21–00:16:15; FFIVE, 01:16:36–01:16:56; Hub, 01:24:02–01:24:48 | Distinguir custo da energia, preço ao motorista, receita da plataforma e margem do operador. |
| Clareza e atratividade da interface | Amps, 00:23:36–00:23:43 | Funcionalidade e design importam juntos. A banca precisa entender a ação e seu resultado imediatamente. |
| Demonstração prática | WeCharge, 00:29:27; FFIVE, 01:16:06–01:16:22 | Integração física ajuda, desde que o vídeo explicite quais dados e ações são reais e quais são simulados. |
| Venda da solução | ChargeGrid de 1CCPG, 00:37:27–00:37:40; FFIVE, 01:15:35–01:15:53 | Apresentar a transformação no negócio, em vez de enumerar abas. |
| Novos problemas operacionais | Overstay, 00:43:13–00:43:30 | Existe espaço para diferenciais além das premissas, quando ligados a disponibilidade, receita ou experiência. |
| Uso simples e português | ChargeGrid Intelligence, 01:07:50–01:08:30; Smart HMI, 00:59:09–00:59:39 | Vocabulário familiar, poucos passos e alternativas ao celular têm valor concreto. |
| Disciplina de tempo | Regra de quatro minutos, 00:02:22–00:02:54; encerramento de ChargeOps, 01:30:57 | A evidência central precisa aparecer antes do limite. Não reservar a melhor demonstração para o final. |

O padrão mais útil é a recorrência das perguntas sobre demanda. A banca não se satisfaz apenas com “temos gestão inteligente”. Ela procura uma cadeia compreensível: entrada de dados, limite, decisão, aplicação e resultado. O encerramento em 01:36:40–01:37:05 reforça que saber mostrar o projeto afeta a seleção.

## Mapa das doze apresentações

| Ordem | Projeto e identificação | Início do pitch | Ideia central | Questão mais importante |
| --- | --- | --- | --- | --- |
| 1 | Smart Charge | [00:04:30](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=270s) | Ecossistema comercial com carteira, incentivos e gestão energética | Qual parte da previsão e da distribuição já funciona com dados reais? |
| 2 | Asset Charge, grafia a confirmar | [00:11:36](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=696s) | Tarifa variável conforme solar e demanda | Separar configuração atual das previsões e automações futuras. |
| 3 | Amps, equipe 6 | [00:18:58](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=1138s) | Integração e otimização energética com previsão | Como foram validados modelos, restrições e conectores reais? |
| 4 | WeCharge, equipe 7 de 1CCA | [00:25:00](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=1500s) | Hardware, recomendação de estação e modos de recarga | A demonstração precisa ser narrada e o controle precisa ser explicável. |
| 5 | ChargeGrid de 1CCPG | [00:33:15](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=1995s) | Jornada integrada entre motorista, painel e operador | Quais pagamentos e mudanças de potência são integrações e quais são simulações? |
| 6 | Projeto sobre overstay, equipe 4 de 1CCPH | [00:39:57](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=2397s) | Reduzir ocupação da vaga após a recarga | Como comprovar saída física e automatizar demanda? |
| 7 | Voodoo Recharge, grafia a confirmar, equipe 1 de 1CCPI | [00:45:46](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=2746s) | Telemetria e comandos com confirmação via MQTT | Pagamento e demanda ficaram pouco elaborados na resposta. |
| 8 | Smart HMI, equipe 2 de 1CCPI | [00:53:49](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=3229s) | Interface no carregador e perfis residenciais | RFID e chat foram posteriormente identificados como simulações. |
| 9 | ChargeGrid Intelligence, equipe 3 de 1CCPI | [01:02:43](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=3763s) | Gestão de dados, demanda e sustentabilidade | Qual a metodologia das previsões e dos indicadores ambientais? |
| 10 | ChargeGrid da F5 ou FFIVE, equipe 1 de 1CCPK | [01:11:19](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=4279s) | Operação comercial com aplicativo e painel ESP32 | Sustentar demanda, tarifação e margem com comportamento demonstrável. |
| 11 | ChargeGrid Intelligence Hub, equipe 3 de 1CCPK | [01:19:56](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=4796s) | Cobrança por uso, faturamento e balanceamento preventivo | Preço ao cliente precisa remunerar também a operação. |
| 12 | ChargeOps Assistant, equipe 5 de 1CCPK | [01:26:46](https://www.youtube.com/watch?v=MFYoHv4j3KQ&t=5206s) | Camada comercial, balanceamento e assistente | A ferramenta completa não ficou visível dentro do pitch. |

## Ranking das apresentações

Este é um ranking de **força do pitch considerando também a consistência do que foi sustentado nas perguntas**. Não é uma auditoria dos produtos. As posições próximas, especialmente de 2 a 5 e de 6 a 9, podem mudar com os slides, o vídeo integral e a rubrica. Não foram atribuídas notas decimais porque a evidência não sustenta essa precisão.

| Posição | Projeto | Avaliação | Motivo da posição |
| --- | --- | --- | --- |
| 1 | ChargeGrid de 1CCPG | Muito forte | Narrativa dirigida à GoodWe, jornada integrada e demonstração de mudança de demanda. A banca diz que se sentiu convencida a comprar. |
| 2 | Amps | Muito forte | Melhor explicação técnica de previsão e decisão; integração, caixa e precificação ligados a uma proposta comercial. Falta evidência independente da execução. |
| 3 | Smart Charge | Muito forte | Cobertura ampla e conectada das premissas; incentivos de demanda e fidelidade. A banca confirma explicitamente a completude. |
| 4 | ChargeGrid da FFIVE | Forte | Boa venda, modelo de receita e demonstração física. A resposta sobre demanda e tarifa é menos objetiva do que a proposta inicial. |
| 5 | ChargeGrid Intelligence Hub | Forte | Fluxo claro do consumo ao faturamento, comprovante e alertas. O argumento de rentabilidade precisa melhorar. |
| 6 | Projeto sobre overstay | Competitivo | Dor específica, fácil de lembrar, com efeito operacional e pagamento integrado segundo a fala. Gestão energética manual limita a proposta. |
| 7 | Asset Charge | Competitivo | Explicação simples e aderente de tarifa solar e demanda. Parte dos diferenciais mais atraentes está nos próximos passos. |
| 8 | WeCharge | Competitivo com ressalva de apresentação | Boa integração física descrita e dois modos de recarga. Vídeos pouco narrados e controle esclarecido apenas nas perguntas. |
| 9 | ChargeGrid Intelligence | Intermediário | Boa cobertura analítica e tema ambiental. Menos foco narrativo, metodologia pouco explicada e perguntas centrais respondidas depois. |
| 10 | Smart HMI | Intermediário | Proposta de display tem mérito. Início pouco ligado à dor comercial; demanda manual e funcionalidades simuladas enfraquecem aderência. |
| 11 | Voodoo Recharge | Frágil no conjunto | Boa engenharia descrita de comandos e telemetria, mas pagamento e demanda permanecem rasos; acesso à demo atrapalha o esclarecimento. |
| 12 | ChargeOps Assistant | Frágil no conjunto | Ideias comerciais e protótipo físico interessantes, mas tempo mal distribuído. A própria banca pede para ver mais da ferramenta montada. |

**Melhor venda:** ChargeGrid de 1CCPG. **Melhor argumento de gestão energética:** Amps. **Ecossistema mais abrangente no discurso:** Smart Charge. **Dor mais específica e memorável:** overstay. **Melhor oportunidade da FFIVE:** combinar sua base integrada com uma prova curta de operação confiável e um resultado econômico explicável.

Os dois últimos são os pitches mais frágeis deste conjunto, não necessariamente os produtos tecnicamente piores. O Voodoo, por exemplo, descreve confirmação pelo dispositivo com mais clareza do que vários concorrentes melhor posicionados.

## Análise individual dos projetos

### Smart Charge

**Proposta e funcionalidades.** Levar recarga a pequenos estabelecimentos, com rede, solar e bateria; aplicativo do motorista e painel do lojista; mapa, reservas, histórico, carteira com Pix, crédito e boleto, QR e interface local. Descreve assistência por IA e previsão de demanda. Apresenta três modalidades de fidelidade: cashback, níveis por gasto e créditos de recarga por consumo na loja. Afirma API própria, integrações externas e 91 testes de segurança e 81 funcionais. Essas quantidades são alegações da equipe, não resultados conferidos.

**Diferencial real do discurso.** Em 00:07:06–00:07:26, conecta restrição energética a incentivos: o motorista aceita menor consumo ou potência em troca de benefício. Isso transforma gestão de demanda em escolha comercial compreensível. A nomenclatura de potência e energia está imprecisa na transcrição; não permite reconstruir o algoritmo.

**Força e fragilidade.** A banca reconhece abrangência das premissas em 00:09:08–00:09:56. O risco é parecer completo demais sem mostrar quais componentes realmente funcionam. A alegação de disponibilidade permanente de energia depende de capacidades e condições que não foram demonstradas.

**O que aproveitar.** Usar os cupons existentes da FFIVE em uma campanha simples vinculada à loja e, depois, a uma condição energética observável. Validar quem financia o desconto e se ele preserva margem. Carteira, níveis e três mecanismos de fidelidade simultâneos têm custo de implementação maior e pouco ajudam se cobrança básica ainda estiver pendente.

### Asset Charge

**Proposta e funcionalidades.** Seleção no mapa, disponibilidade, potência, tarifa, rota externa, sessão com custo e tempo, histórico e assistente. O gestor vê recargas, receita, solar, demanda, manutenção e configuração de tarifa e distribuição. A tarifa depende de demanda e disponibilidade solar.

**Separação importante.** Previsão de saída por histórico, previsão de pico, ajuste automático de tarifa, alertas mais ricos e integração com GoodWe e veículos aparecem como **próximos passos**, em 00:13:46–00:14:55. Não devem ser contabilizados como entregas atuais. Existe uma lacuna de transcrição antes do feedback; não cabe julgar o fechamento visual.

**Força e fragilidade.** Boa organização e explicação acessível. A banca valoriza relação entre solar, pico e tarifas, inclusive condições de faturamento do estabelecimento. Contudo, não são apresentados indicadores de qualidade das previsões nem evidência suficiente de automação energética.

**O que aproveitar.** Mostrar o motivo do preço e opções de horário ao usuário. A FFIVE já compara preço e transfere orçamento para a recarga; isso facilita uma evolução para ofertas por horário, desde que as condições sejam explícitas. Só anunciar previsão personalizada depois de existir histórico adequado e comparação com uma estimativa simples.

### Amps

**Proposta e funcionalidades.** Produto integrado ao ecossistema GoodWe e adaptável a estações compatíveis, com referência a OCPP e Modbus. Pré-pagamento por valor, operação pelo caixa sem instalar aplicativo e várias formas de pagamento. Tarificação considera energia, demanda, custos fixos e margem.

**Diferencial técnico.** Em 00:21:19–00:22:33, descreve duas previsões, consumo do estabelecimento e demanda dos carregadores, em passos de 15 minutos e horizonte de 12 horas. O planejamento é recalculado com novos dados, com otimização matemática para decisões. Explica que não usa chamadas de IA generativa nesse controle, embora exista custo de processamento.

**Força e fragilidade.** É a proposta tecnicamente mais articulada da gravação. A banca também aprecia coerência visual com a plataforma existente. Entretanto, a fala não revela dados de treinamento, erro de previsão, comparação com referência, restrições detalhadas ou testes em equipamentos GoodWe. Planejar comunicação por um protocolo não comprova integração.

**O que aproveitar.** Começar por regras transparentes e um simulador de cenários, medindo resultado contra distribuição igual. Operação pelo caixa é uma boa alternativa posterior para usuários sem conta. Não competir com promessas de machine learning sem possuir dados e resultados próprios.

### WeCharge

**Proposta e funcionalidades.** Maquete com Arduino, RFID e sensor de luz representando solar. Aplicativo com mapa e recomendação de estação; painel da loja com recargas e decisões; administrador de toda a rede. A equipe afirma conexão entre app e painel e uso de OpenAI. Nas perguntas, descreve modos urgente e econômico e redução da capacidade disponível quando o estabelecimento consome mais.

**Diferencial.** Apresentar interação física e preferências de recarga ajuda a tornar o produto tangível. A descrição de motivos das decisões no painel também tem valor. Urgente e econômico, porém, não são novos espaços para a FFIVE reivindicar exclusividade.

**Força e fragilidade.** A banca elogia simulação prática, mas pergunta como a demanda é gerida. Há longos trechos sem fala transcrita durante vídeos, e o professor orienta explicitamente a narrá-los em 00:30:58–00:31:09. Isso limita a capacidade de vender o benefício dentro de quatro minutos. A relação entre urgência, fonte solar e velocidade depende do caso; não pode ser generalizada.

**O que aproveitar.** Uma preferência de economia ou saída rápida, acompanhada de limite e estimativa, pode aproveitar o planejamento da FFIVE. Cada decisão deve mostrar os dados usados e respeitar os limites elétricos; o assistente pode explicar decisões calculadas pelo controle.

### ChargeGrid de 1CCPG

**Proposta e funcionalidades.** Apresentação começa no contexto da GoodWe e usa uma passagem coordenada entre integrantes. Descreve cadastro, veículos, mapa, rota, histórico e código de conexão. O painel permite identificação ou visitante, escolha de recarga, custo e potência. O operador acompanha demanda, consumo, financeiro e indicadores.

**Demonstração mais valiosa.** Em 00:35:39 mostra potência limitada por consumo do estabelecimento; em 00:36:26–00:36:43 reduz esse consumo e descreve aumento automático da potência e remoção do aviso. Há integração explicada entre ação, estado e interface. A equipe também informa que bateria e estação são randomizadas para simulação.

**Força e fragilidade.** O elogio em 00:37:27 é o sinal verbal mais forte de venda da gravação. Não prova, porém, que Pix/cartão sejam liquidados, que exista medição física ou que o algoritmo opere no HCA G2. Os números de mercado e a lei mencionada não foram adotados como fatos verificados neste relatório.

**O que aproveitar.** Repetir a estrutura de demonstração causal: alterar uma entrada, explicar a decisão e mostrar o resultado nas duas interfaces. A FFIVE pode fazer isso com confirmação e falha de comunicação que já existem; para repetir o exemplo de potência, precisa construir primeiro o controle correspondente.

### Projeto sobre overstay de 1CCPH

**Proposta e funcionalidades.** Parte de uma dor operacional específica: veículo permanece na vaga após terminar. Descreve notificações, cadastro de veículo, mapa, início por QR ou código, informação de bateria fornecida pelo usuário, estimativa, parada, histórico e painel comercial. Afirma checkout Stripe. Nas perguntas, esclarece gestão manual de potência e triagem de suporte por IA com encaminhamento humano.

**Diferencial.** Overstay liga disponibilidade a receita e é valorizado pela banca como algo além das premissas. A estatística de 75% citada no pitch não vem com referência verificável na transcrição; não deve entrar no pitch da FFIVE sem uma fonte e definição do indicador.

**Força e fragilidade.** Narrativa focada, demonstração curta e bom uso do tempo. Alertar o fim da recarga pode reduzir ocupação, mas não comprova que o veículo saiu. Não há evidência suficiente de sensor de vaga, fila automatizada ou cobrança de ocupação. Gestão elétrica depende da ação do operador.

**O que aproveitar.** Notificação de conclusão e uma oferta de vaga para o próximo motorista formam uma evolução útil. Antes de anunciar “vaga livre”, obter evidência de desconexão e, quando necessário, ocupação física. Um toque em “saí” não garante disponibilidade real.

### Voodoo Recharge

**Proposta e funcionalidades.** ESP32 publica via MQTT; serviço Python e painel recebem leituras; comandos aguardam confirmação do equipamento. A equipe declara uma vaga ligada ao equipamento e outras cinco simuladas, limites de potência, separação solar/rede, parada remota e automática, além de histórico usado para calcular cobrança.

**Diferencial.** Explica bem a diferença entre enviar comando e confirmar aplicação, em 00:46:33–00:46:41. Afirma latência inferior a um segundo e leituras a cada dois segundos; não há logs conferidos nesta análise. Isso impede a FFIVE de dizer que confirmação pelo dispositivo é uma ideia exclusiva.

**Força e fragilidade.** A banca elogia arquitetura, mas pede demanda e pagamento. Durante o esclarecimento, há dificuldade de acesso à demo. Em 00:51:24–00:51:33 a equipe admite pagamento ainda teórico e pouco elaborado; em 00:51:57–00:52:11 admite gestão de demanda pouco desenvolvida além de um limite. A unidade desse limite varia na transcrição, exigindo cuidado com julgamento técnico.

**O que aproveitar.** Mostrar a evidência de ACK da FFIVE e preparar acesso e backup para as perguntas. Complementar isso com recuperação, idempotência e efeito para o motorista oferece uma narrativa mais completa do que apenas comparar latências.

### Smart HMI

**Proposta e funcionalidades.** Interface acoplada ao carregador, com perfis residenciais, metas, agendamento, início local, atividade, diagnóstico e configurações. Na versão comercial, identificação por RFID, QR e app; gestor controla múltiplas estações, operações e potência. Uso sem celular e proposta offline aparecem no esclarecimento.

**Força e fragilidade.** A banca aprecia inclusão de quem tem dificuldade com aplicativo e o painel operacional. Entretanto, o argumento inicial de telas deixarem produtos mais sofisticados é menos forte que explicar redução de erro ou autonomia. Demanda é manual. O chat é admitido como simulador em 01:00:37–01:00:42. Após a afirmação de três métodos funcionais, o RFID é identificado como ainda sem hardware em 01:01:24–01:01:35.

**O que aproveitar.** A FFIVE já tem display touch físico e parada local. Pode destacar instruções claras na bancada e linguagem acessível. Isso não autoriza anunciar recarga comercial offline: sua política atual para perda de comunicação encerra a sessão simulada, e novos inícios dependem de autorização. Perfis e funcionamento offline exigem desenho próprio.

### ChargeGrid Intelligence de 1CCPI

**Proposta e funcionalidades.** Parte de quatro carros solicitando 80 kW em uma instalação com 60 kW. Apresenta dashboard, solar, rede, faturamento, previsão consultiva, risco de pico, relatório de sustentabilidade, histórico e alertas. Mostra cadastro de veículo e início/fim de sessão.

**Esclarecimentos.** Nas perguntas, descreve distribuição igual da capacidade e tarifa por horário/demanda com variação de 10% a 15%. A transcrição não permite confirmar a execução automática dessas regras. A previsão usa o histórico futuro como argumento, mas não traz avaliação de desempenho. Os indicadores de CO₂ e economia não vêm com metodologia suficiente.

**Força e fragilidade.** Cobertura analítica ampla; sustentabilidade é bem recebida. Entretanto, a demonstração percorre muitos indicadores e deixa a lógica central para as perguntas. A banca pede português em termos destinados ao usuário final.

**O que aproveitar.** Um painel compacto com limite, consumo do prédio, solar, potência alocada e motivo da restrição tem mais efeito do que muitos gráficos. Se houver indicadores ambientais, mostrar origem, período, fator e cenário de referência; não apresentar estimativa como crédito de carbono.

### ChargeGrid da FFIVE

**Proposta e funcionalidades no pitch.** App em Python, área de consumidor e vendedor, mapa, histórico, recarga, cupons, reservas de dez minutos e painel ESP32. O discurso inclui tarifa por pico/rotatividade, Pix/cartão, autenticação e chatbot ainda em desenvolvimento. Sugere receita variável por transação, com média semanal de 25%, e cenário de um ponto de 22 kW utilizado oito horas por dia.

**Força.** A banca elogia venda, fechamento, apresentação e demonstração com QR. Existe uma base integrada no repositório que sustenta parte importante da proposta. O código atual acrescenta comparação de pontos, orçamento, estados pendentes visíveis e registro de eventos, portanto já permite uma apresentação mais madura do que a de 25/09.

**Fragilidade.** A resposta sobre demanda diz que, ao atingir um limite, os outros pontos teriam metade da potência. Isso não demonstra que a soma final ficará dentro do limite. O discurso sobre tarifa mistura pico, rotatividade e saldo; são mecanismos diferentes. No código atual, a tarifa é fixa por ponto e congelada na sessão; pagamento real, carteira e balanceamento geral não aparecem implementados.

**O que ajustar.** Dar uma resposta numérica e demonstrável para demanda; distinguir preço, incentivo e ocupação; corrigir receita bruta versus lucro; apresentar o chat local como orientação e consulta à conta. Se IA externa e pagamento entrarem na próxima versão, demonstrar seus resultados antes de anunciar entrega.

### ChargeGrid Intelligence Hub de 1CCPK

**Proposta e funcionalidades.** Painel com seis conectores, indicador preventivo a 80%, tarifas por horário, comprovante com energia/duração/valor, faturamento, ticket médio e exportação CSV. Assistente responde sobre tarifa. Jornada guiada, mapa dos conectores como planta e central de alertas completam a proposta.

**Força e fragilidade.** A banca destaca fluxo claro e diferenciais explicados. A ligação entre sessão e faturamento é bem apresentada. Entretanto, cálculo de valor e comprovante não evidenciam confirmação de pagamento por provedor. O limiar de 80% não revela por si só a regra de distribuição. A banca aponta que cobrar apenas o custo da energia pode não remunerar a infraestrutura.

**O que aproveitar.** Transformar o resumo de sessão da FFIVE em documento legível, com origem da energia e status financeiro separado quando existir pagamento. Exportação e alertas ajudam o operador, mas devem respeitar propriedade dos dados. Um resumo atual de custo estimado não é comprovante financeiro.

### ChargeOps Assistant

**Proposta e funcionalidades.** Modelo de receita com venda de sistema, assinatura e taxa por recarga. Explica limites, temperatura, bateria, divisão de capacidade e fator por horário. Descreve chatbot com proteções contra prompt injection. A demonstração física aparece somente após o limite, a pedido da banca, com ESP32, RFID e carga de celular controlada pelo site.

**Força e fragilidade.** Tem consciência comercial e interação física útil. Porém, perde tempo em explicação de variáveis e deixa a melhor evidência fora dos quatro minutos. Em 01:32:33–01:32:44 admite que a coleta de dados da recarga está prevista para depois. Em 01:34:17–01:34:29 a banca diz que queria ver mais da ferramenta montada. Isso pesa mais que elogios genéricos de encerramento.

**O que aproveitar.** Mostrar hardware cedo e colocar regras em um exemplo simples. Não repetir o raciocínio de que um carro próximo de cheio “desperdiça” toda potência nominal disponível: potência permitida e potência efetivamente consumida são diferentes. Controle de temperatura também não deve ser anunciado sem leitura correspondente. As ambiguidades da transcrição devem ser verificadas no vídeo antes de atribuir erro definitivo à equipe.

## O que o seu aplicativo já possui

O principal cuidado é distinguir o pitch de setembro, a versão anterior simulada e a implementação integrada atual. O README define a bancada como integração de aplicativo, API e painel com **sensores simulados**, sem acionar carregador, medir veículo ou processar pagamento.

| Funcionalidade | Situação no estado local | Valor competitivo e limite |
| --- | --- | --- |
| Cadastro, login e autorização | Implementados com Supabase Auth e validação na API | Base operacional; confirmação de e-mail está desativada no ambiente documentado. Recuperação depende de SMTP configurado. |
| Perfis de motorista e operador | Implementados, com autorização por propriedade | A troca visual de perfil não concede acesso a equipamentos de terceiros. |
| Vinculação do equipamento | QR privado, segredo separado do código público, vínculo de proprietário | Reduz a dificuldade de adicionar equipamento e oferece um argumento de operação por vários lojistas. |
| Postos e múltiplos pontos | Cadastro, configuração, publicação e histórico por proprietário | Estrutura para vários equipamentos; não equivale a balanceamento de carga entre eles. |
| Mapa, busca e rota externa | Implementados | Já cobre parte importante da jornada comum aos concorrentes. Distância de comparação é aproximada em linha reta. |
| Filtro e comparação | Conector, disponibilidade, preço e proximidade | Os atributos exibidos correspondem ao mesmo ponto elegível; não combinar preço de um ponto e disponibilidade de outro. |
| Planejamento antes de reservar | Por orçamento ou tempo, com intenção levada à revisão | Boa base para escolha assistida. A estimativa usa potência nominal e tarifa; não garante energia ou horário de saída. |
| Reserva | Com confirmação do dispositivo e prazo de chegada | Ajuda a reduzir incerteza. Não promete que uma vaga física desocupada foi medida por sensor. |
| Identificação no local | Código de presença rotativo exibido no painel | Exige o código atual para autorizar o início; não constitui prova absoluta da presença física se o código for compartilhado. |
| Início e parada | Comandos, estados pendentes e confirmação pelo dispositivo | A interface distingue pedido e aplicação, evitando sucesso antecipado. |
| Limites de duração e custo | Implementados no controle da bancada | Encerram a sessão simulada. A política precisa ser novamente validada com medição e atuador reais. |
| Atualização e recuperação | Aviso de informação antiga, reconciliação, proteção contra repetição e parada local por perda de comunicação | Diferencial técnico útil, que precisa virar uma história compreensível para a banca. |
| Tarifa e cupom | Preço por kWh configurável, desconto e congelamento por sessão | Transparência básica. Não há motor de tarifa automática por demanda, solar ou horário. |
| Histórico e resumo | Sessões, estimativa, origem e motivo de encerramento | Ajuda a entender a operação. Não é comprovante de pagamento. |
| Eventos de sessão | Persistência local implementada e endpoint para o titular | Registra pedidos, ACKs, falhas e reconciliação observada. Depende da nova migração no ambiente em que será demonstrado. |
| Operação | Resumo, postos, estado online, configurações, cupons e acesso ao histórico | O resumo financeiro soma custos estimados; não demonstra receita liquidada ou lucro. |
| Chat | Orientação local e consultas explícitas à recarga, reserva e histórico | É funcional para essas tarefas. Não utiliza IA externa, não abre chamados e não executa pagamentos. |
| Painel ESP32 touch | Interface e sincronização reais documentadas | A bancada usa potência, energia e bateria simuladas. Não apresentar como carregamento de carro. |
| Experiência e acessibilidade | Temas, contraste, foco, navegação e melhorias verificadas em prévia web | Ainda faltam validações documentadas de leitor de tela nativo, Android e participantes reais. |

As evidências de código estão em [modelos](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/models.py>), [descoberta de pontos](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/stations/routes.py:33>), [planejamento](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/mobile/src/chargegrid_app/services/planning.py:5>), [autorização de início](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/service.py:52>), [eventos](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/routes.py:62>) e [controle da bancada](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/firmware/esp32/src/charging_controller.cpp>).

### Lacunas importantes no seu produto atual

| Lacuna | Consequência para a competição | Primeira entrega recomendada |
| --- | --- | --- |
| Pagamento por provedor e conciliação | Premissa comercial ainda sem prova; concorrentes alegam integrações | Checkout em ambiente de testes, confirmação recebida do provedor e vínculo com a sessão. |
| Gestão agregada de demanda | Não é possível sustentar a afirmação de controle automático da instalação | Modelo de instalação, consumo base, solar e restrições, com alocação demonstrada em cenário reproduzível. |
| Tarifação por horário ou condição energética | O pitch descreve mais do que o código atual oferece | Ofertas com vigência, motivo e valor aceito antes de iniciar; preservar contrato durante a sessão. |
| Medição e atuação em equipamento real | A comunicação funciona, mas não entrega nem mede energia de veículo | Confirmar o contrato de integração com a GoodWe e demonstrar uma operação compatível quando houver acesso. |
| Atendimento com IA externa, se exigido pela rubrica | Chat atual não comprova requisito de IA generativa | Consulta a dados autorizados e respostas com fonte; controle elétrico continua em regras verificáveis. |
| Notificações fora da tela aberta | Acompanhamento exige iniciativa do usuário | Evento de conclusão e alteração relevante com entrega verificável. |
| Ocupação física, fila e overstay | Sessão concluída não comprova vaga liberada | Evidência de desconexão/ocupação e política de oferta ao próximo usuário. |
| Métricas de margem e operação | Há custos estimados, mas falta valor econômico defensável | Resultado por sessão, falhas, tempo de liberação e premissas de custo separadas. |

### Diferenças entre as promessas do pitch e o código

Em 01:13:02–01:13:10 são citados Pix, cartão, alteração de senha e autenticação. A implementação atual sustenta autenticação e parte da gestão de conta; **não processa Pix ou cartão**. Em 01:17:02–01:18:35 são citados limite geral, tarifa por rotatividade e saldo. O esquema atual não contém carteira, tarifa progressiva ou controlador de limite agregado. O chat hoje está na interface, mas é um assistente local de orientação e leitura autorizada; não é a IA externa descrita como ainda em terminal na banca.

Não é necessário reduzir a ambição do projeto. É necessário organizar a apresentação em **entregue, demonstração controlada e próxima integração**, com uma evidência para cada afirmação. Isso evita que uma boa resposta comercial se torne vulnerável em perguntas técnicas.

## Diferenciais dos concorrentes que valem incorporar

| Ideia | Onde aparece | Relação com a FFIVE | Prioridade sugerida |
| --- | --- | --- | --- |
| Pagamento integrado | Smart Charge, Amps, overstay; outros descrevem Pix/cartão | Falta o fluxo financeiro verificável | Alta, por aderência comercial. |
| Mudança de potência visível | ChargeGrid de 1CCPG | Falta o controle que liga consumo da instalação à decisão | Alta, por recorrência da pergunta da banca. |
| Tarifação explicável | Asset, Amps, Smart Charge e Hub | Configuração fixa e orçamento já oferecem base | Alta depois de separar custo e preço. |
| Incentivo por flexibilidade | Smart Charge | Cupons existentes podem apoiar um experimento simples | Média; medir margem e aceitação. |
| Urgente e econômico | WeCharge | Evolução natural das intenções de tempo e orçamento | Média; explicar viabilidade e restrições. |
| Caixa sem aplicativo | Amps | Novo canal de acesso com autorização do operador | Média, sobretudo para comércio; não é um gap exclusivo. |
| Fim de recarga e overstay | Equipe 4 de 1CCPH | Falta evento de notificação e ocupação física | Média, com boa força narrativa. |
| Comprovante e exportação | Hub | Histórico atual já possui parte das informações | Média; distinguir resumo de recibo financeiro. |
| Perfis de uso no display | Smart HMI | Painel físico existente pode facilitar repetição de preferências | Baixa a média, conforme público escolhido. |
| Previsão energética | Amps; Smart Charge; consultiva no Intelligence | Falta histórico adequado e referência de qualidade | Posterior às regras e coleta; não começar pela previsão. |
| Indicadores ambientais | ChargeGrid Intelligence | Não existem fontes para sustentar impacto físico na bancada atual | Posterior à medição; mostrar metodologia antes de benefícios. |
| Carteira e vários níveis de fidelidade | Smart Charge e intenção da FFIVE | Criam saldo, obrigações e conciliação adicionais | Adiar até a cobrança básica estar fechada. |

Mapa, QR, histórico, dashboard e chatbot aparecem repetidamente. São elementos de cobertura, com pouco valor de exclusividade isoladamente. Mesmo hardware físico e ACK estão presentes em outras equipes. A vantagem precisa vir da qualidade da jornada, da prova e do resultado.

A própria GoodWe já anuncia controle automático de potência, agendamento, autenticação e integração com SEMS+ para o HCA G2. **Inferência de produto:** a FFIVE deve explicar qual problema comercial e operacional acrescenta ao ecossistema existente. Apenas replicar controle e monitoramento oferecidos pelo fabricante dificulta defender o valor da nova camada. [Página oficial HCA G2](https://br.goodwe.com/carregadores-hca-g2-goodwe).

## Oportunidades pouco ou nada evidenciadas nos pitches

As propostas abaixo são hipóteses de diferenciação dentro desta amostra. Não constituem pesquisa de novidade no mercado. Cada uma exige confirmação de demanda com usuários ou operadores.

### Recuperação completa e explicável da operação

**Gap observado.** Nenhum pitch demonstra a sequência completa de comando pendente, perda de comunicação, política local, retorno, conciliação da sessão e conciliação financeira. Voodoo já descreve ACK; Smart HMI propõe uso offline. A oportunidade está na recuperação coordenada e na clareza para o usuário.

**Produto mínimo.** Linha do tempo da sessão com estado financeiro separado: pedido enviado, ponto confirmou, dados ficaram antigos, sessão terminou pela política local, sincronização retornou e custo foi revisado. Se houver pagamento, informar autorização, valor confirmado, cancelamento ou ajuste. O registro de eventos da FFIVE já cobre parte operacional; a parte financeira ainda precisa ser implementada.

**Benefício e prova.** Menos incerteza sobre se a recarga iniciou, terminou ou foi cobrada duas vezes. Demonstrar um pedido repetido, um retorno após falha e a manutenção de uma única sessão. Medir duplicações, tempo de reconciliação e necessidade de intervenção, sem chamar o histórico atual de registro inviolável ou completo de todas as indisponibilidades.

### Energia necessária até o horário de saída

**Gap observado.** Há modo urgente, previsão de saída planejada e divisão igual. Não há demonstração de um plano que teste a viabilidade de entregar uma quantidade mínima de energia até um prazo e explique a impossibilidade quando as condições mudarem.

**Produto mínimo.** Usuário informa “preciso de 6 kWh até 17h e quero gastar até R$ 20”. O sistema calcula se a potência disponível permite atender o pedido e mostra alternativas. Começar em kWh evita inventar autonomia em quilômetros; conversão para autonomia exige dados apropriados do veículo e condições de uso.

**Benefício e prova.** O motorista ganha uma decisão útil antes de reservar; o operador distribui capacidade por necessidade e prazo. Não prometer entrega garantida com dados de potência nominal. No piloto, chamar de plano estimado e atualizar o resultado quando consumo do prédio ou solar mudarem.

### Distribuição justa e motivos compreensíveis

**Gap observado.** Smart Charge oferece incentivos e WeCharge prioridade urgente. Vários dividem igualmente. Não é evidenciada uma política transparente que combine prazo, energia mínima, tempo de espera e prevenção de usuários ficarem indefinidamente sem capacidade.

**Produto mínimo.** Definir uma regra simples, explicar por que cada ponto recebeu sua parcela e mostrar alternativa ao usuário prejudicado. Quando não houver capacidade mínima suficiente, pausar ou enfileirar conforme restrições do equipamento. A política deve considerar acesso justo, inclusive para quem não compra prioridade.

**Benefício e prova.** O operador entende e consegue defender a decisão. Comparar, com as mesmas entradas, distribuição igual e regra por prazo; medir metas atendidas e tempo de espera. Maior potência para um usuário não pode ultrapassar limite da instalação nem ser chamada de redução automática do consumo total de energia.

### Disponibilidade com evidência de ocupação e validade

**Gap observado.** Todos vendem disponibilidade no mapa, e uma equipe trabalha overstay. Não se demonstra a ligação completa entre dispositivo atualizado, reserva, carro/cabo presente, desocupação e oferta ao próximo motorista.

**Produto mínimo.** Separar “ponto comunica”, “aceita nova sessão”, “há reserva” e “vaga física disponível”. Exibir validade do dado quando houver falha. Uma fila voluntária só recebe oferta quando houver evidência suficiente de liberação, com prazo para aceitar e política contra reservas acumuladas.

**Benefício e prova.** Evitar que o usuário se desloque para um ponto falsamente disponível. A FFIVE já possui disponibilidade vinculada a estado e reconciliação; falta comprovar ocupação física. Percentual histórico de confiabilidade depende de intervalos de observação suficientes, não da simples ausência de eventos de falha.

### Receita incremental da loja e margem por recarga

**Gap observado.** Smart Charge já vincula fidelidade à loja e a FFIVE já tem cupons. Nenhum pitch demonstra atribuição de receita adicional, comparação de campanha e margem líquida da sessão após os custos relevantes.

**Produto mínimo.** Ligar campanha a sessão e cupom resgatado, separar receita de recarga, custo energético estimado e custo do benefício. Um resumo do operador mostra o resultado por sessão e campanha, com hipóteses claramente visíveis.

**Benefício e prova.** O lojista avalia se a recarga traz vendas e se o desconto compensa. Sem grupo de comparação, a associação entre cupom e compra não comprova que a campanha causou a venda. Para a final, um cálculo transparente e um plano de piloto são melhores que inventar retorno comercial.

### Assistente com respostas verificáveis sobre a própria operação

**Gap observado.** Há chatbots, respostas sobre tarifa e suporte escalonado. Não é evidenciada uma resposta que vincule explicação de custo ou falha à linha do tempo, aos dados autorizados e às condições aceitas pelo usuário.

**Produto mínimo.** Pergunta: “Por que minha recarga parou?” Resposta usa motivo registrado, horário observado, origem e ação seguinte. Pergunta: “Por que deu esse valor?” Resposta usa energia, preço aceito, cupom e status de pagamento. Identificar falta de dados e impedir acesso à sessão de outra conta.

**Benefício e prova.** A IA passa a resolver um problema de atendimento concreto. A consulta local atual e os eventos oferecem base. O assistente explica cálculos e fatos; limites elétricos, preços e decisões financeiras continuam determinados por regras e autorização verificáveis.

## Sequência recomendada para aumentar a competitividade

Sem o prazo e a rubrica da final, a priorização abaixo considera as premissas repetidas nesta banca. O esforço é relativo à base atual, não uma estimativa de dias. A apresentação final deve usar apenas as entregas verificadas na versão que será demonstrada.

| Ordem | Entrega | Por que vem antes | Esforço relativo | Critério de conclusão |
| --- | --- | --- | --- | --- |
| 1 | Matriz de afirmações e evidências | Corrige divergências entre pitch e produto imediatamente | Baixo | Cada afirmação tem tela, registro ou ensaio correspondente e identifica simulação. |
| 2 | Pagamento de uma sessão em ambiente de testes | Fecha uma premissa comercial central | Médio a alto | Pagamento confirmado pelo provedor, repetição sem duplicação, falha e cancelamento demonstrados. |
| 3 | Controle de demanda com cenário reproduzível | Responde à pergunta mais recorrente da banca | Alto | Soma de potências respeita limites em todos os cenários escolhidos; decisão e aplicação aparecem separadas. |
| 4 | Oferta por horário e explicação de preço | Liga economia do motorista à margem do operador | Médio | Preço aceito e regra têm vigência; sessão não sofre alteração inesperada; custo da energia fica separado. |
| 5 | Demonstração de falha e recuperação | Usa a vantagem da base já integrada | Baixo a médio para a prova; maior para conciliação financeira | Uma sessão permanece identificável antes e depois da falha; estados e origem são compreensíveis. |
| 6 | Plano por energia e prazo | Acrescenta uma decisão útil pouco evidenciada nos concorrentes | Alto | Sistema reconhece pedidos viáveis e inviáveis e mostra a mudança após nova condição. |
| 7 | Notificações, fila e ocupação | Melhora rotatividade e reduz deslocamento frustrado | Médio a alto | Oferta da vaga depende de evidência de liberação e possui prazo e regra verificáveis. |
| 8 | Margem, campanhas e piloto com pessoas | Sustenta valor comercial com dados | Médio, com dependência de participantes | Premissas, resultados observados e resultados ainda não medidos ficam separados. |

**Se só houver espaço para três frentes:** cobrança verificável, controle de demanda explicável e recuperação de sessão. A demonstração deve mostrar como as três se conectam. Carteira, múltiplos programas de fidelidade, predição avançada, ERP, relatórios extensos e crédito de carbono ficam atrás desse núcleo.

Há uma decisão de produto importante: escolher um **público principal** para a final. Pequeno comércio com alguns pontos é coerente com cupons e operação comercial; condomínio prioriza rateio e regras de uso. Os dois podem compartilhar infraestrutura, mas misturar suas dores durante quatro minutos dilui a proposta. Recomenda-se comércio como hipótese inicial para esta apresentação, deixando condomínio como expansão, até que o enunciado ou a validação indiquem outro recorte.

### Uma demonstração numérica de demanda

Este é um **cenário didático proposto**, não um resultado do ChargeGrid atual. Considere limite de importação da rede de 30 kW, prédio consumindo 18 kW, produção solar local de 6 kW e margem de 2 kW. Suponha ainda que o circuito dos carregadores suporte a alocação e que não haja bateria de armazenamento neste exemplo.

Capacidade para os carros = mínimo entre o limite do circuito e o máximo de zero com **30 − 18 + 6 − 2 = 16 kW**. A soma de importação, consumo e solar só vale quando as medidas e os limites correspondem ao mesmo ponto elétrico, sem contabilizar solar duas vezes.

| Condição | Potência dos carros | Importação calculada | Resultado |
| --- | ---: | ---: | --- |
| Três carros pedem 7,4 kW cada, sem limite agregado | 22,2 kW | 18 + 22,2 − 6 = 34,2 kW | Ultrapassa 30 kW. |
| Controle aplica a capacidade calculada | 16 kW | 18 + 16 − 6 = 28 kW | Preserva a margem de 2 kW. |
| Solar cai a zero, outras condições iguais | 10 kW | 18 + 10 = 28 kW | Recalcula a capacidade disponível. |
| Consumo do prédio sobe para 25 kW, sem solar | 3 kW | 25 + 3 = 28 kW | Pode exigir pausa ou fila, conforme mínimos dos carregadores. |

Dentro dos 16 kW, uma regra por prazo poderia alocar 7,4 kW para A e 4,3 kW para B e C, em vez de aproximadamente 5,33 kW para cada um. Isso só é útil se A tiver uma meta mais urgente, as restrições dos equipamentos permitirem e B/C não ficarem indefinidamente prejudicados. É exemplo de alocação, não prova de redução de energia ou de atendimento garantido.

No produto real, considerar também limites de corrente por fase, potência aceita pelo veículo, mínimos do carregador, sensores antigos, transição entre decisões e confirmação da aplicação. O HCA G2 tem integração com o ecossistema GoodWe, mas a existência de OCPP, Modbus ou acesso de terceiros no modelo e firmware utilizados deve ser confirmada com documentação e permissão técnica; não foi estabelecida nesta análise.

**Implicação concreta no repositório:** o firmware atual recebe START, STOP, RESERVE e RELEASE, além de operações de manutenção. `SimulatedSensors` usa 7.200 W fixos enquanto carrega. Alterar `power_kw` cadastrado não significa comandar potência no dispositivo. A evolução exige contrato de controle, estado desejado e observado, ACK, simulador correspondente e, posteriormente, integração real compatível.

### Cobrança com estados próprios

Criar um vínculo entre sessão e operação financeira, preservando a diferença entre **valor estimado**, **valor final calculado** e **pagamento confirmado**. Se usar autorização prévia, a captura final deve considerar a sessão conciliada; se usar pré-pagamento, definir como tratar encerramento antecipado e saldo não consumido. Escolher um desses fluxos para a primeira prova reduz complexidade.

Os cenários mínimos são: sucesso, provedor indisponível, notificação recebida duas vezes, recarga que não inicia e recarga que termina antes do previsto. O navegador voltar do checkout não basta como prova de pagamento. A confirmação deve vir da integração autorizada com o provedor. Na apresentação, o ambiente de testes fica visível e nenhuma transação de demonstração é apresentada como receita real.

### Preço dinâmico com contrato compreensível

Uma primeira versão pode variar ofertas para **novas sessões**, congelando a tarifa aceita no início. A gestão de potência pode reagir a condições elétricas sem elevar silenciosamente o preço de uma sessão em andamento. Uma tarifação por faixas durante a sessão exige regra e aceite mais detalhados; não é necessária para a primeira entrega.

Separar quatro elementos na interface e no cálculo: custo energético do operador, preço comercial ao motorista, benefício concedido e eventual taxa por ocupação. Ocupação após término é diferente de consumo de energia. A tarifa também depende de modalidade e distribuidora: a ANEEL distingue ponta e fora de ponta no Grupo A e os três postos da Tarifa Branca do Grupo B. Portanto, horário e grupo devem ser parâmetros do estabelecimento, sem uma faixa universal presumida. [Postos tarifários da ANEEL](https://www.gov.br/aneel/pt-br/assuntos/tarifas/entenda-a-tarifa/postos-tarifarios).

## Revisão do modelo de receita apresentado pela FFIVE

Em 01:13:32–01:13:44, o pitch combina 22 kW, R$ 2,15 e oito horas diárias. A fala transcrita diz “por hora”, mas o resultado de aproximadamente R$ 11 mil é compatível com **R$ 2,15 por kWh**, durante 30 dias e à potência constante. A correção da unidade deve ser feita no slide e na fala, após conferir o vídeo original.

Nesse cenário: 22 × 8 × 30 = **5.280 kWh**; multiplicando por R$ 2,15/kWh, a receita bruta é **R$ 11.352/mês**. Uma taxa de 25% representa **R$ 2.838/mês de receita bruta da plataforma**. Não é lucro da plataforma nem do eletroposto.

Para mostrar sensibilidade, use as hipóteses explícitas abaixo. O custo de R$ 0,90/kWh é **inventado para exercício**, não uma tarifa pesquisada. Todos os cenários supõem a mesma potência de 22 kW efetivamente usada durante o tempo indicado; uso por carros de menor potência reduz a energia e a receita.

| Uso por dia em 30 dias | Energia | Receita a R$ 2,15/kWh | Taxa de 25% | Energia a R$ 0,90/kWh | Sobra do operador antes dos demais custos |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0,5 hora | 330 kWh | R$ 709,50 | R$ 177,38 | R$ 297,00 | R$ 235,12 |
| 2 horas | 1.320 kWh | R$ 2.838,00 | R$ 709,50 | R$ 1.188,00 | R$ 940,50 |
| 8 horas | 5.280 kWh | R$ 11.352,00 | R$ 2.838,00 | R$ 4.752,00 | R$ 3.762,00 |

Os valores usam centavos; a comissão é arredondada antes de calcular a sobra do operador. Ainda faltam tributos, tarifas financeiras, manutenção, equipamento, instalação, aluguel ou uso da vaga, consumo auxiliar, perdas, suporte e infraestrutura de software, quando aplicáveis. Não há evidência para concluir que o custo operacional se resume ao servidor.

**Recomendação:** apresentar a taxa de 25% como hipótese a validar, com três cenários de utilização, custos e benefício ao operador. Explicar o que a plataforma entrega por essa taxa. Assinatura por ponto e taxa por transação também são hipóteses comerciais; escolher um modelo para testar ajuda mais do que acumular formas de monetização. Nenhum pitch desta gravação demonstra disposição real a pagar ou lucro de piloto.

## Quantas equipes poderiam passar

### Corte global entre as trinta equipes

O título do arquivo e o encerramento em 01:35:49–01:35:59 identificam Top 30 para Top 15. Há apenas 12 pitches nesta gravação e **18 equipes não observadas**. Não há base para prever resultado oficial ou probabilidade individual calibrada.

A tabela interpreta o pedido de intervalos de cinco e dez como cortes globais hipotéticos. O cenário neutro é **12 × vagas ÷ 30**, assumindo qualidade distribuída de forma semelhante entre manhã e restante. A faixa subjetiva é uma hipótese de planejamento, não intervalo estatístico; os dados não permitem calibrá-la.

| Corte global | Referência neutra de classificados desta gravação | Faixa subjetiva para planejamento | Leitura prática |
| --- | ---: | ---: | --- |
| Top 30 | 12 | 12 | Todas as equipes aqui já chegaram a esse grupo. |
| Top 25 | 10 | 9 a 12 | Corte amplo; maior risco nos últimos pitches deste ranking. |
| Top 20 | 8 | 7 a 10 | Disputa provável no bloco intermediário. |
| Top 15 | 6 | 5 a 8 | Os cinco primeiros têm argumento forte; overstay e demais competitivos disputam a margem. |
| Top 10 | 4 | 3 a 5 | Prioridade para os primeiros quatro ou cinco, condicionada às outras bancas. |
| Top 5 | 2 | 1 a 3 | Exige disputar com a elite das outras 18 equipes. Boa apresentação, sozinha, não garante vaga. |

O palpite central para esta amostra é **seis classificados no Top 15, quatro no Top 10 e dois no Top 5**. Não é uma previsão baseada nas notas oficiais. A competição pode selecionar mais ou menos equipes da manhã, e não foi evidenciada cota por turma ou horário.

Mantida a avaliação relativa, os nomes mais fortes para essas vagas são ChargeGrid de 1CCPG, Amps e Smart Charge, seguidos de FFIVE e Hub. Overstay tem diferenciação suficiente para ultrapassar um projeto mais genérico se a rubrica valorizar problema operacional. WeCharge poderia subir ao se verificar que os vídeos mostram melhor implementação do que a transcrição permite perceber.

### Se o corte fosse apenas entre os doze pitches

Com cinco vagas, a escolha deste relatório seria: ChargeGrid de 1CCPG, Amps, Smart Charge, FFIVE e ChargeGrid Intelligence Hub. Overstay é a primeira alternativa.

Com dez vagas, entrariam os dez primeiros da tabela de ranking; Voodoo Recharge e ChargeOps Assistant ficariam fora. Isso é uma simulação local, distinta do corte global anunciado.

### Situação da FFIVE

**Na gravação, eu posiciono vocês em quarto, com faixa plausível de terceiro a quinto.** Há argumento para classificação e o feedback é favorável. O salto para uma vaga de Top 5 global exige evidência mais forte nas premissas centrais e uma história clara de diferencial.

Uma forma precisa de entender a incerteza: mantendo a quarta posição relativa e o mesmo critério para todas as equipes, a posição global seria **4 + o número de equipes não vistas que ficariam acima de vocês**. Pode variar de 4 a 22. Para Top 15, no máximo 11 das 18 não vistas poderiam superar vocês; para Top 10, no máximo 6; para Top 5, no máximo 1. Isso explica por que uma boa posição na banca da manhã não garante o Top 5 global.

O código local de outubro parece oferecer uma história de confiança mais forte do que o pitch de setembro, mas a nova versão não foi apresentada à banca neste material. Sua qualidade futura não foi usada para aumentar retroativamente a posição no ranking.

## Como organizar a apresentação final

Escolher uma promessa verificável: **o motorista sabe o que foi confirmado e o operador consegue explicar o uso e o resultado da recarga**. Quando cobrança e demanda estiverem implementadas e verificadas, elas entram nessa mesma jornada.

O roteiro abaixo soma **3min50s**, com dez segundos de margem para uma regra de quatro minutos. Essa duração vem da banca analisada; confirmar se a final mantém o formato. Todo recurso futuro citado depende de entrega e validação antes de ser usado como demonstração.

| Tempo | Mensagem e ação | Prova |
| --- | --- | --- |
| 0:00 a 0:20 | Apresentar um lojista com vários pontos e um motorista com orçamento e horário | Uma dor concreta, sem estatística de mercado sem fonte. |
| 0:20 a 0:40 | Explicar por que a camada comercial complementa o equipamento GoodWe | Fluxo do motorista ao operador, com escopo explícito. |
| 0:40 a 1:15 | Comparar pontos, definir orçamento, reservar e confirmar no painel | Mostrar pedido pendente e confirmação recebida. |
| 1:15 a 2:00 | Alterar consumo do estabelecimento e explicar distribuição | Somente se o novo módulo existir; mostrar cenário e limites, identificando simulação. |
| 2:00 a 2:35 | Encerrar e mostrar resumo e pagamento | Somente se integrado; ambiente de testes e confirmação do provedor separados do custo. |
| 2:35 a 3:10 | Mostrar falha, política local e recuperação em gravação de apoio narrada | Não esperar os 45 segundos do watchdog ao vivo; indicar que é gravação de ensaio. |
| 3:10 a 3:35 | Mostrar resultado para operador e modelo comercial | Uma métrica observada e cenários econômicos com hipóteses. |
| 3:35 a 3:50 | Fechar com diferencial e proposta de piloto | Uma ação concreta para continuar a validação, sem prometer premiação. |

Se os módulos de pagamento e demanda não estiverem prontos, usar o espaço para demonstrar a jornada integrada atual e apresentar esses módulos como próximos passos. Isso preserva credibilidade, embora a lacuna de aderência comercial continue relevante.

Não deixar vídeo sem narração. Para cada trecho, dizer a entrada, a mudança e o benefício: “O pedido chegou; o ponto ainda não confirmou; por isso o aplicativo continua aguardando”. Usar palavras como ponto, potência, energia, preço e custo com significado consistente. Evitar listar tecnologias por mais de alguns segundos.

Preparar respostas para as perguntas que efetivamente apareceram na banca:

| Pergunta | Resposta que a equipe deve conseguir sustentar |
| --- | --- |
| Como vocês controlam demanda? | Mostrar limite, consumo do prédio, solar, capacidade resultante, distribuição e confirmação. Sem o módulo novo, reconhecer a configuração individual atual. |
| O que acontece se cair a internet? | Explicar o watchdog local de 45 segundos da bancada, preservação e reconciliação. O servidor não conclui que parou só porque ficou offline. |
| O pagamento funciona? | Mostrar provedor e confirmação no ambiente correspondente. Se não existir, responder que há estimativa de custo, sem pagamento implementado. |
| Isso já controla o HCA G2? | Distinguir integração real app, API e ESP32 de futura atuação no carregador GoodWe. |
| A bateria e a energia são medidas? | Informar que o protótipo atual utiliza sensores simulados e mostrar a origem. |
| Como a IA decide? | Explicar qual tarefa usa IA e quais regras determinam controle, autorização e cobrança. O chat local atual não é IA externa. |
| O operador ganha quanto? | Separar receita e custos, mostrar cenários de utilização e não chamar comissão de lucro. |
| Por que a GoodWe adotaria? | Demonstrar o problema comercial ou operacional acrescentado à plataforma, além de monitoramento e potência. |
| Qual é o diferencial diante dos outros? | Mostrar recuperação, fatos observados e decisão útil; evitar alegar exclusividade de QR, hardware, mapa ou ACK. |
| O usuário consegue entender? | Apresentar tarefas realizadas por participantes, erros e compreensão, quando esses testes tiverem sido feitos. |

## Evidências que mais ajudariam antes da final

1. **Ensaio integrado da versão final:** reserva, confirmação, início, limite, parada, histórico, falha e retorno. Registrar versão do app, API, firmware e origem dos dados.
2. **Pagamento em ambiente de testes:** registrar uma operação de sucesso e outra de falha, incluindo repetição da confirmação e vínculo com a sessão.
3. **Comparação do controle:** mesma sequência de demanda com e sem a política, indicando violações do limite e metas atendidas. São resultados simulados enquanto não houver instalação medida.
4. **Cinco participantes exploratórios:** escolher ponto, informar orçamento, reservar, iniciar e interpretar falha. Medir tempo, ajuda, erro e compreensão. Esse número serve para descobrir problemas, não generalizar comportamento do mercado.
5. **Conversa com operador real:** confirmar dor, condições de acesso ao equipamento e interesse em piloto. Disposição a pagar só é evidência se efetivamente investigada; não foi obtida nesta análise.
6. **Material de apoio:** vídeo narrado, credenciais de demonstração disponíveis à equipe, tabela de afirmações e evidências e alternativa de apresentação se a rede falhar.

Não aumentar contagem de testes apenas para competir com os números de outro pitch. Um ensaio que mostra uma falha relevante e sua recuperação explica melhor o valor. Os registros existentes de 29 e 30/09 são úteis, mas não substituem um ensaio da versão que chegar à final.

## Referências para conferir a análise

| Fonte | Uso |
| --- | --- |
| [Transcrição original](</Users/djmurillo/Library/Containers/net.whatsapp.WhatsApp/Data/tmp/documents/668891EB-2472-430A-852C-2DA221F1FFA2/Transcricao_MFYoHv4j3KQ.md>) | Todas as apresentações e feedbacks; os links de horários permitem localizar as falas no vídeo. |
| [README atual](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/README.md>) | Identificação FFIVE, escopo da bancada e limitações. |
| [Validação da experiência](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/validacao-experiencia-gs.md>) | Testes anteriormente documentados e ausência de novo deploy, APK ou ensaio físico. |
| [Registro de sessão](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/registro-sessao-local.md>) | Eventos observados, isolamento e migração validada apenas localmente. |
| [Modelos da API](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/models.py:57>) | Tarifa por ponto, sessões, dispositivos e ausência de carteira no modelo atual. |
| [Reserva](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/reservations/service.py:12>) | Comando, confirmação e prazo de chegada. |
| [Início de sessão](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/service.py:52>) | Presença, autorização, cupom e tarifa congelada. |
| [Resumo do operador](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/api/app/modules/charging/routes.py:122>) | Total de energia e custo estimado, sem liquidação financeira. |
| [Chat](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/apps/mobile/src/chargegrid_app/screens/chat.py:166>) | Orientação local e consultas autorizadas à conta. |
| [Sensores da bancada](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/firmware/esp32/src/sensors.cpp:4>) | Potência fixa simulada de 7.200 W, energia e SoC gerados. |
| [Protocolo do ESP32](</Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/esp32-protocol.md>) | Comandos, ACK, watchdog e reconciliação. |
| [GoodWe HCA G2](https://br.goodwe.com/carregadores-hca-g2-goodwe) | Recursos anunciados pelo fabricante; não comprova acesso de terceiros ao equipamento do projeto. |
| [ANEEL postos tarifários](https://www.gov.br/aneel/pt-br/assuntos/tarifas/entenda-a-tarifa/postos-tarifarios) | Diferença entre modalidades e necessidade de parametrizar distribuidora e período. |

Os números de mercado, legislação de condomínio, estatística de overstay e percentuais ambientais citados pelos concorrentes não foram incorporados como fatos externos verificados. O relatório prioriza a evidência das apresentações, o código do usuário e oportunidades que possam ser demonstradas na final.
