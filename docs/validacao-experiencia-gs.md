# Experiência ChargeGrid — validação da entrega

Data: 29/09/2026. Implementação integrada e verificação local concluídas.

## Escopo

P0 + P1 e demonstração do plano em `plano-experiencia-gs-2026.md`: home e marca, contraste/acessibilidade, escolha assistida, planejamento antes da reserva, confirmação e atualização dos dados. Histórico avançado e painel analítico (P2) ficam para outra entrega.

Três subagentes implementam áreas distintas, com revisão pelo orquestrador. As mudanças preexistentes de keepalive, configuração Vercel, versão mobile e instalação foram preservadas.

## Verificação da base

- API: 118 testes aprovados em PostgreSQL 16 descartável, isolado em localhost. Inclui testes de isolamento, concorrência, presença, recuperação e comandos existentes.
- Ferramentas: 42 testes aprovados; os dois testes dependentes de banco passaram separadamente no PostgreSQL descartável, totalizando 44.
- Migrações: aplicadas até o head em banco vazio de teste; provisionamento e importação verificados nesse esquema.
- Firmware: validação de host com controlador e interface LVGL reais aprovou autorização, replay, watchdog, limite de custo, parada local, reserva após reinício, restauração e ciclo do QR. Decodificação dos QRs renderizados aprovada.
- Baseline mobile da auditoria: 288 testes e 58 subtestes aprovados.

Esses ensaios não usaram o banco publicado nem gravaram hardware. A validação de host não substitui ensaio no ESP32 físico.

## Resultado final

- Mobile: **314 testes e 87 subtestes aprovados**, incluindo novos cenários de comparação, plano, revisão de condições, atualização e navegação.
- API: **129 testes aprovados** no PostgreSQL 16 descartável, incluindo 11 novos casos de descoberta e paginação.
- Ferramentas: **44 testes aprovados**, conforme a rodada da base; não houve mudanças nessas ferramentas.
- Ruff: código e testes mobile/API aprovados. `git diff --check` aprovado.
- Prévia web: home verificada em 360 × 800 nos temas escuro e claro; ação principal no topo. Fluxo manual na conta demo percorreu orçamento de R$ 10 → comparação → reserva → presença → revisão com R$ 10 → início pendente → recarga → parada pendente. Capturas em `images/app-home-gs-dark.png` e `images/app-home-gs-light.png`.
- Botões/abas usam controles nativos com foco e seleção; testes verificam contraste dos tokens/badges e ausência de altura fixa nos componentes principais. A árvore de acessibilidade foi inspecionada na prévia web. Tab alcançou “Cheguei: informar código” e Enter abriu a etapa de confirmação; o wizard também foi conferido em 1280 × 800.

Problemas encontrados e corrigidos durante a revisão:

1. Atualização manual podia continuar após a troca de tela: tarefa agora é cancelada e respostas antigas não marcam a tela nova como atualizada.
2. Retorno do wizard apagava contexto da busca: filtros, localização e intenção acompanham o contexto de retorno, preservando isolamento por conta.
3. Comparação podia sugerir atributos de pontos diferentes: o contrato vincula preço, potência, conector e estado ao mesmo ponto elegível.
4. Revisão poderia usar condições antigas: novo início reconsulta o ponto e exige outra revisão após mudança de tarifa, potência ou limite. Pedido incerto mantém corpo/chave originais.
5. Filtros e cartões secundários afastavam ações importantes: comparação recolhe após aplicação, “Cheguei” aparece cedo e parada precede detalhes secundários.
6. Contraste de badge verde e linguagem ambígua foram ajustados; potência/energia usam formatação local, e o painel não afirma energia entregue.

## Limites e próximos ensaios

Não houve novo APK, publicação de backend, migração em ambiente remoto, gravação ou ensaio em ESP32 físico. A versão publicada e os APKs existentes não recebem automaticamente estas alterações.

Não foi realizado teste com leitor de tela nativo, escala de fonte do Android ou participantes reais. A inspeção web e os testes estruturais não constituem certificação de acessibilidade. Persistem dois avisos de depreciação do Flet e dois das dependências do TestClient, sem falha nas suítes.

Consultas filtradas por disponibilidade/preço avaliam os estados dos candidatos antes da paginação; os atributos estáticos restringem candidatos no SQL. A consulta padrão/proximidade sem filtros continua paginada no SQL. Antes de ampliar o catálogo, medir e otimizar carregamento de disponibilidade em lote.

## Ajuste de interface após revisão do usuário

- Retirada a faixa de “Consulta atualizada” das consultas bem-sucedidas. Ela aparece somente em falha, com o último horário conhecido e a ação para tentar novamente.
- Removido o cartão “Guia de recarga” da home. O Chat segue acessível na navegação principal.
- A conta demo e suas credenciais aparecem apenas com `CHARGEGRID_ENABLE_DEMO=1` em desenvolvimento. O mesmo controle bloqueia login direto pelo e-mail demo e o método de entrada programática quando desligado. O script de prévia local habilita a opção explicitamente; a configuração padrão é desligada.

## Cenários de aceite da implementação

| Área | Cenário | Evidência requerida |
| --- | --- | --- |
| Descoberta | Ordenar por preço/distância com mais resultados que uma página | Ordenação e filtro executados antes de limitar a página. |
| Descoberta | Posto com conector barato indisponível e outro compatível disponível | Preço, conector e recomendação correspondem ao mesmo ponto elegível. |
| Descoberta | Sem coordenadas, nenhum resultado, tarifa zero e valores inválidos | Mensagem útil; nenhuma proximidade inventada ou conversão inválida. |
| Planejamento | Informar orçamento ou minutos e abrir a revisão | Intenção preservada; cálculo consistente; potência nominal identificada. |
| Planejamento | Voltar etapas, reservar e depois chegar, sair da conta | Preservar contexto válido; limpar dados da conta anterior. |
| Confirmação | Comando solicitado sem confirmação do equipamento | Interface permanece pendente; nenhum início ou encerramento inventado. |
| Atualização | Falha de rede, tentativa manual, recuperação e troca de tela | Aviso persistente; informação anterior identificada; callback antigo não altera tela nova. |
| Layout | 360 × 800 e tela ampla, claro e escuro | Ação principal visível, texto legível e ausência de sobreposição. |
| Acessibilidade | Teclado, seleção de aba, texto ampliado | Papel/estado/foco compreensíveis e conteúdo alcançável. |
| Demonstração | Fluxo completo na conta isolada | Nenhum acesso necessário a credenciais, banco ou equipamento real. |

## Demonstração para a banca

Proposta de duração: aproximadamente quatro minutos, adaptável ao regulamento.

1. Apresentar a hipótese de dor e a promessa “Recarga com confirmação, do app ao ponto”.
2. Escolher conector, orçamento/tempo e comparar opções.
3. Reservar e mostrar que o próximo passo depende da confirmação do equipamento.
4. Iniciar, acompanhar e encerrar; explicar a origem das medidas.
5. Em ensaio integrado separado, demonstrar perda de comunicação e reconciliação, respeitando o watchdog real.

O enunciado/rubrica e o prazo da turma não foram fornecidos. A matriz oficial de aderência e testes com participantes reais continuam dependendo desses insumos. Nenhum resultado de pesquisa com usuários ou impacto ambiental foi presumido.
