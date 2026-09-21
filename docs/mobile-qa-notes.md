# Revisão mobile — 21/09/2026

## Escopo e evidência

Foram revisados os módulos de autenticação, navegação, preferências, API/sessão e todas as telas: início, postos, reservas, recarga, histórico, perfil, ajuda, cupons e operador. Esta nota registra testes locais de callbacks reais e transporte HTTP controlado; não os apresenta como testes visuais em Android ou como confirmação física do ESP32. A validação de navegador/API publicada, compilação APK e integração física é conduzida separadamente pelo coordenador.

Comandos reproduzíveis, na raiz do projeto:

```sh
PYTHONPATH=apps/mobile/src .venv/bin/python -m unittest discover -s apps/mobile/tests -v
.venv/bin/ruff check apps/mobile/src apps/mobile/tests
```

Resultado nesta revisão: **64 testes aprovados**, lint limpo.

## Comportamentos verificados

| Fluxo | Evidência local |
| --- | --- |
| Cadastro | Seleção consumidor/vendedor preserva nome/e-mail/senha; envia `account_type`; confirmação de e-mail abre a tela correta; botão e Enter simultâneos produzem somente uma requisição. |
| Login | Senha chega intacta ao cliente, inclusive espaços e credencial antiga curta; login/logout/login usa o mesmo segredo; perfil persistido determina destino; vendedor pendente nunca recebe acesso de operador. |
| Sessão | Refresh antes do vencimento, um único refresh para dois 401 concorrentes, limpeza após rejeição do token renovado, reconexão recria o transporte e exige login. |
| Idempotência | Reenvio após timeout conserva chave; leitura `current=null` não descarta intenção incerta; recarga terminal conhecida libera a chave correspondente para uma nova recarga no mesmo ponto. |
| Tema | Claro/escuro isolados por contexto de execução; seletor respeita o tema da conta; preferência sobrevive a nova instância e utiliza `FLET_APP_STORAGE_DATA`; JSON inválido ou de formato inesperado não impede abertura. |
| Navegação | Back nativo cancela o pop da View e abre o pai lógico em cadastro, recarga e subáreas; início permite saída; histórico do operador preserva ID do posto na paginação. |
| Postos | Latitude/longitude incompletas são rejeitadas; raio/coordenadas têm limites; polling alterna corretamente o estado vazio; posto sem conectores é descrito como “Sem pontos”, sem falsas ações disponíveis. |
| Recarga | Transição para terminal reconstrói ações; código explícito não reabre sessão antiga; duração/custo inválidos são barrados; início pelo posto respeita seu limite padrão; polling retoma após indisponibilidade temporária. |
| Início | Atualiza reserva/recarga, resumo e disponibilidade a cada 10 s, sem reconstruir a lista/rolagem; não redesenha quando os dados permanecem iguais. |
| Cupons | Formulário não contorna aprovação de operador; percentual precisa ser inteiro; validade futura em dia/mês/ano hora:minuto é convertida para UTC. |
| Gestão | Cupons selecionam postos pelo nome e mostram ativo/inativo. Edição de conector consulta metadados do dispositivo proprietário, sem recuperar chaves; ausência, revogação e novo provisionamento atualizam os controles. |
| Layout | Estrutura dos controles verifica campos esticados, botões de 48 px, campos de autenticação de 50 px, largura máxima e rótulos; cores e SafeArea foram revisados no código. |

## Correções relevantes da segunda revisão

- `Preferences.load()` falhava com JSON válido que não fosse objeto e interpretava `"false"` como verdadeiro. Agora recupera o padrão de forma segura e aceita somente booleano.
- Mensagem “Nenhum posto encontrado” permanecia após chegada de postos pelo polling. Sua visibilidade acompanha o resultado atual.
- Posto sem conectores era mostrado como ocupado; passou a indicar ausência de pontos.
- Nova recarga com os mesmos parâmetros podia reaproveitar chave de uma sessão já concluída. As chaves passam a ser associadas à sessão confirmada e retiradas quando seu estado terminal é conhecido.
- Dois pedidos que recebessem 401 simultaneamente podiam renovar tokens duas vezes. A comparação usa o token efetivamente rejeitado.
- Back Android passou a usar `View.can_pop`/`on_confirm_pop` do Flet instalado, sem persistir ou repetir operações antigas. O callback e o destino foram testados; o gesto/botão físico ainda exige validação no APK.

## Limites conhecidos

- Login não é restaurado depois de fechar o app ou perder a sessão de interface. É uma decisão explícita do MVP (`planejamento-mvp.md`, autenticação): tokens só ficam em memória; não foram gravados em arquivo sem proteção. Uma recarga física continua sendo reconciliada após novo login.
- Rotas internas não são URLs/deep links nem uma pilha de histórico do navegador. Back Android usa pais lógicos; a prévia web usa links e abas do aplicativo.
- Preferência de tema é por instalação/processo de hospedagem, não sincronizada na conta. Cada sessão ativa tem paleta isolada; uma prévia web hospedada compartilha a preferência inicial de arquivo entre sessões.
- E-mail de confirmação/recuperação depende do provedor e SMTP configurado; sucesso da requisição não comprova entrega à caixa postal.
- Mapa depende de tiles externos e pode recorrer ao mapa esquemático. Essa integração está sendo validada separadamente pelo coordenador.
- Aprovação de vendedor continua administrativa; selecioná-lo no cadastro não concede gestão de postos.
- Nenhum teste local de controle/HTTP substitui observação do LCD físico, do botão Back Android, do teclado virtual e do comportamento após suspensão real do sistema operacional.
