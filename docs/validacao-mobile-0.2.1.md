# ChargeGrid mobile 0.2.1 — animações e navegação

Validado em 21/09/2026. APK build 11, pacote `br.com.ffive.chargegrid`.

## Alterações

- Transição entre telas com fade de 220 ms e saída de 120 ms. A tela anterior permanece visível durante a consulta; o indicador de carregamento só aparece após 180 ms, evitando flashes em respostas rápidas.
- Resposta de toque, opacidade de operação em andamento e hover suave nos botões; transição de cor no seletor de tipo de conta e destaque da aba atual.
- Respeita `disable_animations`/`reduce_motion` informado pelo sistema. Se a consulta à preferência falhar, usa a versão sem movimento. Carregamento reduzido usa texto estático.
- Voltar visível nas telas internas, com destinos lógicos para posto, ponto, cupons e reserva. Voltar não dispara início, parada nem cancelamento de recarga.
- Formulários alterados pedem confirmação antes de navegar, sair da conta ou reconstruir a tela para trocar o tema. Continuar editando preserva os campos; salvar o perfil atualiza o estado de alterações pendentes.
- Cliques repetidos e operações concorrentes são bloqueados. Navegação não cancela uma operação em andamento. Polling não substitui a tela durante início/parada/salvamento ou confirmação de descarte.
- Repetir a aba atual não recarrega o formulário. “Tentar novamente” continua recarregando após falha.

## Evidências

- `PYTHONPATH=apps/mobile/src .venv/bin/python -m pytest apps/mobile/tests -q`: **80 aprovados**.
- Ruff: limpo em código e testes do mobile.
- Navegador real, API publicada e conta QA existente: login, início, perfil, edição temporária, Voltar, continuar editando, descartar, proteção na troca de tema, tema claro e escuro. Edição temporária descartada, sem salvar dados de perfil.
- Inspeção visual em 390 × 844 e no viewport desktop; campos, botões, cabeçalho e navegação inferior conferidos.
- Build Android concluído; assinatura APK v2 válida; versão e build conferidos com `aapt`. Código empacotado comparado com o código atual; configuração pública presente, sem `.env`, credenciais de QA ou testes no pacote.

## Limites

- Não havia Android conectado ao ADB: o gesto/botão Voltar físico e a preferência de animação do Android não foram testados em aparelho. Seus handlers e estados foram exercitados nos testes automatizados; a interação visual foi validada no navegador.
- Esta atualização não altera API, firmware nem protocolo ESP32. A validação física da bancada pertence ao relatório da versão 0.2.0.
- Os testes auxiliares executados nesta rodada tiveram 28 aprovados e um ignorado por falta da configuração do banco descartável de importação. Não houve alteração nesses utilitários.

## Artefato

`builds/chargegrid-0.2.1.apk`

SHA-256: `63c4381dd8fbaaac487699ed428c22032f809cf792264fc6c488aefda1625cbb`

Instalar o APK atualizado é necessário para obter as mudanças no Android.
