# 10 — Previsão de demanda energética

Planejamento de 01/10/2026. Esta frente entra depois da simulação, do balanceamento e dos agregados históricos. Não altera código nem executa treinamento, testes ou integração. Segue [as diretrizes](00-diretrizes.md): RFID e separação solar/rede excluídos; SEMS+ somente como adaptador futuro autorizado; OpenRouter gratuito e MCP explicam fatos produzidos pelo serviço comum.

## Estado atual e limite da promessa

`apps/api/app/models.py` guarda energia cumulativa e última observação da sessão; `Telemetry` registra dispositivo, sessão, boot, sequência, captura, recebimento e payload. `modules/devices/service.py:271` persiste amostras aproximadamente a cada trinta segundos, ou em transições/ACKs. O sync mais frequente não significa histórico igualmente frequente. A validação atual rejeita regressão energética e captura futura excessiva, mas não comprova sozinha uma série temporal ordenada, completa e representativa.

`tools/maintenance.py:13` permite excluir telemetria anterior a sete dias quando chamado com `--apply`; não há evidência aqui de execução automática dessa limpeza. Produzir agregados duráveis antes de remover amostras é requisito para observar sazonalidade. Os totais finais não reconstroem o consumo por horário.

O simulador atual usa 7.200 W; a conta demo mantém dados em memória e reinicia ao sair, conforme `docs/demo.md`. Isso serve para demonstrar contratos, não sustenta previsão real. Consumo predial persistente, limites aplicados e intenção energética são propostas das frentes [01](01-simulacao-sems.md) e [02](02-demanda.md).

## Alvo, horizonte e experiência

O MVP prevê **potência média agregada dos carregadores em cada janela de cinco minutos**, em W, para os próximos trinta ou sessenta minutos: seis ou doze valores. O alvo corresponde à energia entregue na janela dividida pelo tempo, não à potência nominal cadastrada. Prever Wh por janela seria outra representação desse mesmo alvo, com conversão declarada, sem somar cumulativos.

O maior valor previsto é o **pico de potência média de cinco minutos**. Não representa pico instantâneo nem demanda faturável da concessionária. Máximo observado de `power_w`, chegadas, ocupação e consumo predial são alvos separados, com datasets e métricas próprias; não entram silenciosamente no MVP. Um alvo futuro de potência total exige carga predial cuja fronteira exclua carregadores e cobertura simultânea: soma dos dois componentes uma única vez, sem solar/rede.

O operador vê curva, faixa de incerteza, origem, cobertura, atualização e comparação com o baseline. Uma recomendação pode dizer “avaliar adiamento de novas sessões nesta janela”, sempre com justificativa e opção de revisão. A previsão não emite comando, inicia recarga, reajusta preço nem altera tarifa aceita. O controlador determinístico continua responsável pelos tetos, ACK, envelopes reservados e estados desconhecidos.

## Dataset, cobertura e proveniência

Propor agregação compartilhada com [relatórios](09-exportacao-indicadores.md). Cada registro contém `installation_id`, limites UTC `[start,end)`, W médio, Wh observado, segundos elegíveis/cobertos, pontos esperados/conhecidos, origem por segmento, versão da configuração, limite aplicado, flags de qualidade e `available_at`. Calendário usa fuso IANA do posto, inicialmente São Paulo; armazenamento permanece UTC.

Energia de janela vem de diferenças entre leituras válidas da mesma sessão/contador: `ΔWh = Wh_final − Wh_inicial`. Deduplicar boot/sequência; conferir ordenação temporal, reset, regressão, fonte e atraso. Nunca somar valores cumulativos. Não atravessar reboot, sessão diferente ou lacuna extensa supondo potência constante. Um delta tardio pode comprovar energia no intervalo entre capturas, mas não localizar seu consumo em cada subjanela; manter sem distribuição temporal quando faltarem evidências.

Repartição em fronteiras de cinco minutos exige amostras de fronteira ou integração/interpolação explicitamente estimada e validada. Não apresentar essa parcela como medida. Conservar energia total e registrar a metodologia. Potência média precisa de cobertura do conjunto de pontos, incluindo zeros confirmados dentro da validade observada. Desconhecido, offline e dado ausente não viram zero. Não extrapolar total de uma instalação a partir de poucos pontos conhecidos.

Manter `DatasetVersion` com período, unidades, regras, cobertura mínima, hashes e cortes temporais. Uma política inicial proposta exige 95% de cobertura elegível por janela e nenhum ponto ativo desconhecido; é critério de qualidade a revisar, não desempenho comprovado. Janelas incompletas permanecem armazenadas com motivo, mas não recebem alvo completo inventado. Agregados são versionados/reprocessáveis enquanto houver evidências; a limpeza só ocorre após checkpoint confirmado, com retenção definida pelo projeto.

Separar conjuntos simulados, medidos e estimados. Potência observada sob balanceamento representa entrega condicionada à política: não revela quanto o veículo pediria sem restrição. Registrar versão de política e potência aplicada permite identificar esse contexto. Reserva, energia solicitada e horário de saída só entram como atributos opcionais conhecidos no instante da previsão, com qualidade explícita; não são garantia de comparecimento ou demanda.

## Método simples e validação temporal

Comparar duas referências: repetição do último valor válido e mediana histórica da mesma faixa de horário/tipo de dia. A segunda é uma proposta robusta simples, não um modelo já validado. Sem exemplos suficientes para um grupo, usar a primeira com rótulo de fallback; sem último valor fresco, retornar indisponível. Referências simples devem preceder modelos mais complexos, conforme [Hyndman e Athanasopoulos: métodos básicos](https://otexts.com/fpp3/simple-methods.html).

Ajustar somente com observações disponíveis até cada origem de previsão. Avaliar avançando a origem no tempo e medindo todos os horizontes de até sessenta minutos. Separar período final de teste, sem usá-lo para escolher método, limiar, limpeza ou incerteza. As janelas-alvo do treino não podem atravessar o corte; alterações recebidas depois dele não podem entrar retrospectivamente nos atributos. Não embaralhar dias. Essa disciplina segue a [validação temporal com origem móvel](https://otexts.com/fpp3/tscv.html).

Métricas: MAE em W por horizonte, erro absoluto do pico médio em W, erro do horário desse pico em minutos e frequência de localização dentro de uma janela de tolerância previamente definida. Registrar empates e número de casos válidos. Comparar ambos os métodos no mesmo holdout e informar diferença absoluta, sem inventar ganho percentual. MAPE não será usado: consumo zero torna a divisão indefinida, como explica a [avaliação de acurácia](https://otexts.com/fpp3/accuracy.html).

Calibrar uma faixa por horizonte com erros da validação anterior, mantendo teste final intacto; registrar nível nominal, cobertura obtida, largura e tamanho da amostra. Essa faixa requer verificação, não equivale a certeza sobre o próximo pico. Com poucos erros válidos, exibir “incerteza não calibrada”, sem fabricar intervalo. [Referência sobre intervalos de previsão](https://otexts.com/fpp3/prediction-intervals.html).

## Serviços, contratos e execução

Propor `modules/forecasting/` com agregador, baselines, avaliador e `ForecastService`; modelos futuros `DatasetVersion`, `ForecastRun` e `ForecastSnapshot`. Reutilizar autorização e projeções dos relatórios, sem duplicar cálculo no Flet ou MCP. Não adicionar biblioteca pesada antes de haver benefício demonstrado.

Contratos propostos: `GET /v1/installations/{id}/demand-forecast` retorna snapshot autorizado; `POST /v1/installations/{id}/demand-forecast-refresh` agenda trabalho idempotente para operador permitido. Resposta inclui alvo/unidade, resolução, horizonte, `as_of`, `generated_at`, `valid_until`, método/versão, origem, cobertura, pontos previstos, faixa e estado `ready/insufficient/stale/out_of_distribution`. Histórico de avaliações fica separado da resposta curta.

Vercel limita a função atual a trinta segundos (`apps/api/vercel.json`). Atualização usa executor durável, checkpoints e limites de volume; não timer em memória após resposta. GET apenas consulta. MCP lê o mesmo snapshot sob escopo autorizado; o chat OpenRouter explica origem e limites. Modelo de linguagem não recalcula números nem identifica titular pelo texto. Mudança relevante de instalação/política invalida comparabilidade e pode exigir fallback ou suspensão.

## Fases, aceite e demonstração

1. Persistir intervalos e proveniência; provar conservação de Wh, cobertura, lacunas e fronteiras.
2. Criar cenários sintéticos versionados: horário recorrente, chegada irregular, restrição, reboot e ausência. Separar dias e sementes de ajuste, validação e teste; resultado sintético não comprova utilidade real.
3. Implementar baselines, snapshots e comparação temporal; integrar gráfico, relatório e MCP consultivo.
4. Após histórico real suficiente, validar novamente; sofisticar apenas se melhorar a referência sem degradar as métricas críticas.

Prontidão proposta: grupos históricos com ao menos quatro ocorrências válidas, teste final cobrindo dias úteis e fim de semana, métricas por horizonte e faixa verificadas; isso é um mínimo de avaliação, não garantia estatística. Se o candidato não superar a referência escolhida ou houver cobertura insuficiente, manter baseline identificado ou indisponibilidade. Não bloquear gestão de demanda por falta de previsão.

Demo: revelar o período de teste somente depois de congelar método e configuração; mostrar curva prevista, observado, baseline e falhas. Em seguida, retirar uma entrada para demonstrar incerteza/indisponibilidade e consultar o mesmo resultado via MCP. Aceite inclui isolamento entre postos, atualização durável, nenhuma atuação por consulta e nenhuma alegação de previsão real baseada apenas na simulação.
