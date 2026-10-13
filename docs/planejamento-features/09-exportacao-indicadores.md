# 09 — Indicadores comerciais e exportação

Planejamento de 1 de outubro de 2026. Este documento propõe implementação futura; nenhum relatório, biblioteca, migração ou integração é executado nesta rodada. Segue [as diretrizes comuns](00-diretrizes.md): múltiplos formatos, simulação identificada, serviços compartilhados com MCP, sem RFID ou separação solar/rede.

## Estado atual e evidências

- `apps/api/app/modules/charging/routes.py:121`: `/operator/summary` carrega todas as sessões dos postos próprios e soma `energy_wh` e `cost_estimate`, sem janela, status elegível ou segmentação por origem. Não calcula receita confirmada.
- `apps/api/app/modules/users/routes.py:39`: `/me/summary` já calcula o mês em `America/Sao_Paulo`, incluindo sessões concluídas/interrompidas, com energia positiva e término dentro da janela. É uma referência útil, mas sua regra difere do resumo operacional.
- `apps/api/app/modules/charging/routes.py:85`, `:103` e `:135`: históricos pessoais, por posto próprio e do operador são paginados. `apps/api/app/http_helpers.py:81` conta o conjunto completo, retornando apenas uma página.
- `apps/api/app/models.py:121`: sessões guardam tarifa, desconto, energia cumulativa, origem atual, última medição e valor estimado; não há livro de pagamentos, custos ou margem. A origem pode ser `simulated`, `measured` ou `estimated` (`schemas.py:87`) e é atualizada pelo dispositivo (`modules/devices/service.py:219`). Ela não comprova a origem de todo o histórico da sessão.
- `apps/mobile/src/chargegrid_app/screens/operator.py:78` mostra totais estimados e avisa sobre origens misturadas. `screens/history.py:20` busca vinte sessões por página. Eventos detalhados aparecem somente para o titular; a API confirma essa restrição (`modules/charging/routes.py:61`).

## Entrega mínima e indicadores

Criar a área “Relatórios” para motorista e operador, com filtros, indicadores, tabela de prévia e exportação CSV/JSON no primeiro incremento. XLSX/PDF completam a entrega de múltiplos formatos na etapa seguinte, antes de apresentar o recurso como completo. A tela deve explicar cada indicador, período, origem e atualização.

O motorista consulta somente suas sessões. O operador consulta os postos autorizados, com identificador de sessão e dados técnicos mínimos; não recebe telefone, nome, veículo ou identidade do cliente por padrão. O exportador não reutiliza indiscriminadamente `session_row`, que expõe mais campos que um relatório necessita.

Indicadores iniciais: sessões encerradas, energia registrada por origem, valor estimado total, valor médio estimado por sessão elegível, duração observada, motivos de término e sessões interrompidas. Valor médio estimado é soma das estimativas dividida pelo número de sessões encerradas com energia positiva; denominador zero retorna “sem dados”. Sessões pendentes/ativas aparecem separadas, com snapshot e horário, sem entrar nessa média.

Para o relatório de sessões encerradas, usar `ended_at` em intervalo fechado no início e aberto no fim. Atribuir integralmente energia e estimativa à data de término e declarar essa convenção. Isso não equivale a consumo ocorrido naquela janela. Uma sessão atravessando meia-noite não pode ter energia repartida usando apenas o total final: consumo por intervalo exige diferenças entre amostras validadas e cobertura suficiente. Nunca somar amostras cumulativas.

Disponibilidade, utilização e tempo offline dependem de intervalos observados e denominador explícito: tempo monitorado elegível por ponto. Persistir mudanças de estado e fronteiras de validade das observações; após perda de frescor, classificar “desconhecido”. Não transformar ausência de eventos em disponibilidade, parada, ocupação física ou falha. Exibir cobertura conhecida e excluir lacunas da inferência. A telemetria atual, amostrada aproximadamente a cada trinta segundos (`modules/devices/service.py:272`), não substitui esse histórico persistente.

Métricas históricas começam quando existir observação persistida, sem reconstrução fictícia dos meses anteriores. Enquanto a sessão só possuir a última origem, a segmentação deve declarar “classificação atual da sessão”. Para intervalos futuros, guardar proveniência por amostra/segmento; trocar simulador por SEMS+ não converte registros antigos em medidos.

Responsabilidades: o app coleta preferências, apresenta prévia e baixa/compartilha o arquivo; a API calcula, autoriza e renderiza; dispositivo/simulador fornece observações com sequência, instante e origem. O relatório não envia comandos ao equipamento nem depende da futura integração SEMS+. Criar projeção específica de eventos para o operador somente após definir quais fatos técnicos ele pode acessar; preservar a rota exclusiva do titular.

## Uma regra para todos os consumidores

Propor `ReportingService` no backend, responsável por autorização, consulta, projeção permitida, agregação Decimal e contrato versionado. Tela, CSV, JSON, XLSX, PDF e ferramentas MCP recebem o mesmo conjunto normalizado; os adaptadores apenas formatam. Não recalcular valores no Flet, no modelo de IA ou em fórmulas do Excel.

Metadados comuns: `schema_version`, `generated_at`, `as_of`, `timezone`, moeda, unidades, filtros normalizados, critério temporal, contagem completa, origens, cobertura e ressalvas. Datas ficam em UTC no armazenamento e são convertidas pelo fuso IANA selecionado, inicialmente São Paulo. Valores financeiros mantêm precisão Decimal e regra de arredondamento explícita; JSON utiliza strings decimais, preservando precisão.

Paginação afeta somente a visualização. Totais e arquivos cobrem todo o conjunto filtrado. Exportações ordenam de maneira estável por data/ID e usam snapshot consistente; `as_of` sozinho não congela valores de sessões mutáveis. Para comparar vários formatos, gerar um conjunto imutável de relatório, reutilizável pelos adaptadores, ou materializá-lo no trabalho de exportação.

## Opções, campos e contratos propostos

Filtros: início/fim, posto, ponto, status, origem, fuso e ambiente financeiro quando existir. Validar pertencimento de cada posto/ponto no servidor. Filtros inválidos não são silenciosamente ignorados. Selecionar escopo “sessões”, “resumo por dia/posto/ponto” ou “conciliação”, colunas permitidas, ordenação e inclusão de indicadores. Mostrar prévia de vinte linhas, contagem completa e aviso de volume antes da geração.

Campos iniciais: ID de sessão, posto/ponto, status, início/fim, duração, Wh/kWh, tarifa aplicada, desconto, valor estimado, origem registrada, última observação e motivo de término. Origem ausente permanece “não informada”; não assumir medida. Campos obrigatórios de contexto, unidades e origem acompanham qualquer exportação, mesmo quando algumas colunas visuais forem ocultadas.

Contratos novos, todos sob `/v1`:

- `GET /reports/schema`: escopos, formatos, colunas e filtros permitidos para o usuário autenticado.
- `POST /reports/preview`: filtros/escopo/colunas; retorna prévia, totais completos, cobertura e capacidade de geração.
- `POST /report-exports`: solicitação pequena e idempotente, com filtros, colunas, formato, opções e referência ao snapshot; retorna `ready`, `pending` ou erro acionável.
- `GET /report-exports/{id}` e `GET /report-exports/{id}/download`: progresso/metadados e download autenticado, com nova verificação de permissão. Cancelamento e expiração são estados explícitos.

Todos os nomes são propostas. MCP expõe consulta e solicitação desses mesmos serviços com escopos separados; não aceita identidade de titular ditada pelo texto. Clientes externos não recebem arquivo financeiro sem autorização correspondente. Download deve usar HTTP, não conteúdo binário/base64 dentro da resposta do chat.

## Formatos e etapas

| Formato | Finalidade e conteúdo | Etapa |
|---|---|---|
| CSV | Sessões ou agregação tabular para análise; escolher padrão interoperável ou perfil Excel brasileiro, explicitando delimitador/decimal/UTF-8 | MVP |
| JSON | Integrações e IA; envelope com metadados, campos tipados, detalhes e agregados | MVP |
| XLSX | Análise humana; abas Resumo, Sessões e Metodologia, filtros, cabeçalhos fixos e valores calculados no servidor | Segunda |
| PDF | Relatório executivo compartilhável; período, indicadores, gráficos simples, metodologia e anexo opcional | Segunda |

CSV não mistura linhas de totais em detalhes; escopos distintos geram arquivos distintos. JSON usa `null` para indisponibilidade; CSV/XLSX usam célula vazia com legenda. PDF repete cabeçalhos, numera páginas e não corta tabelas: reduzir colunas por escolha explícita, orientar paisagem ou criar anexo. Um resumo pode ser resumido, mas deve declarar a contagem abrangida. Outros formatos, como ODS ou Parquet, só entram por necessidade comprovada; ampliar quatro adaptadores antes da estabilidade aumenta manutenção sem vantagem para a banca.

Planejar `csv`/`json` da biblioteca padrão, XlsxWriter e ReportLab, sem instalar agora. A [documentação Python](https://docs.python.org/3/library/csv.html) sustenta dialetos e escrita por colunas. XlsxWriter documenta [conversão automática de fórmulas/URLs](https://xlsxwriter.readthedocs.io/workbook.html): desabilitá-la e escrever texto não confiável como texto. O [manual ReportLab](https://www.reportlab.com/docs/reportlab-userguide.pdf) descreve tabelas paginadas e cabeçalhos repetidos. Versões e compatibilidade serão verificadas na implementação.

CSV deve neutralizar células textuais capazes de virar fórmulas, incluindo separadores, aspas, controles e prefixos perigosos, e ser validado em Excel/LibreOffice. Isso altera a representação; JSON preserva o texto original. A [OWASP](https://community.owasp.org/attacks/CSV_Injection) alerta que não há saneamento universal para todos os consumidores. Não tratar números negativos legítimos como texto hostil.

## Dinheiro, escala e dependências

Após pagamentos, separar ambiente sandbox/produção, estimativa, cobrança confirmada, reembolso, taxa, repasse e custos informados. Receita confirmada segue o evento financeiro do provedor, não término da sessão; mostrar as duas bases temporais. Carteira: depósito é saldo recebido, não receita de recarga; evitar dupla contagem no consumo. Margem depende de custos completos, com regra e cobertura declaradas; custo ausente nunca significa zero. Cupons atuais não comprovam venda adicional da loja.

A função atual limita execução a trinta segundos (`apps/api/vercel.json:6`), e corpos mutáveis a 16 KB (`app/main.py:111`). Pedidos contêm filtros, nunca todas as linhas. Limitar geração síncrona por volume/tempo medidos; arquivos grandes exigem trabalho persistente, executor durável e armazenamento privado com expiração. Não confiar em tarefa de fundo após resposta serverless. Até essa infraestrutura existir, recusar volume excessivo oferecendo filtro menor, sem truncar silenciosamente. Definir limite de bytes, cotas e prazo; limpar temporários e arquivos expirados. Download usa MIME correto, nome seguro, `Content-Disposition`, `Cache-Control: no-store` e autorização renovada. Mudança de propriedade ou revogação bloqueia a retirada.

## Aceite e demonstração futura

Verificar isolamento entre dois operadores/titulares; fronteiras de mês/fuso; sessão atravessando janela; total completo acima de cem linhas; dados desconhecidos e origens mistas; igualdade entre tela e quatro formatos; texto malicioso, acentos e casas decimais; PDF multipágina; erro de geração, expiração e cancelamento. Pagamento futuro exige replay de webhook, reembolso e saldo sem duplicação.

Na banca, selecionar um posto/período com recargas simuladas, explicar interrupção e cobertura, exportar XLSX para análise e PDF para apresentação, e consultar o mesmo resumo pelo MCP. Mostrar os mesmos números nos três canais e rótulo de simulação. Pendências de implementação: limites de volume, armazenamento/executor e convenção de custos; recomenda-se começar com dados operacionais verificáveis e quatro formatos antes de prometer margem.
