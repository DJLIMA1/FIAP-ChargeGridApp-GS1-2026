# Retomada da versão mais nova — 25/09/2026

Base restaurada: `8ab7df8`, app 0.3.7/build 21 e firmware do painel 0.3.6. Antes da restauração, `apps/api` e `apps/mobile` correspondiam exatamente a `b87eb6c` (reversão temporária da 0.3.5). As correções abaixo são posteriores aos APKs já compilados.

## Falhas reproduzidas e corrigidas

- Repetir um início de recarga aceito podia retornar código expirado ou ambíguo. A API agora recupera a sessão por usuário, chave e corpo antes de resolver o código temporário, mantendo a serialização de pedidos concorrentes.
- Códigos iguais em postos distintos podiam selecionar o posto errado se só um estivesse disponível. A API exige seleção explícita do ponto nesse caso.
- Provisionamento de fábrica e importação legada falhavam com `NOT NULL` em `presence_secret`. A migração `81a24d97be63` adiciona geração aleatória no banco para INSERTs diretos; não substitui segredos existentes nem os exporta nos artefatos de provisionamento.
- O mapa não acompanhava a disponibilidade nem o aparecimento/desaparecimento de postos. Ele passa a atualizar os marcadores, preservando o formulário e evitando renderização quando os dados visuais não mudam.
- Coordenadas e raio não numéricos geravam exceções de conversão. Agora apresentam mensagens de validação ao usuário.

## Verificação

- API: 99 testes aprovados em PostgreSQL 16 descartável, incluindo concorrência, repetição após expiração, colisão entre postos e INSERTs diretos.
- App: 104 testes e 13 subtestes aprovados.
- Ferramentas: 44 testes aprovados, incluindo importação e provisionamento reais no banco descartável.
- Migrações: esquema criado até `6f312d950c41`; ambos os comandos administrativos reproduziram a falha; após `alembic upgrade head`, passaram.
- Ruff e `git diff --check`: aprovados.
- `tools/validate_firmware.py --decode-qr`: controlador e tela LVGL compilados para host; testes de autorização, replay, watchdog, limites, reserva após reboot, restauração e QR aprovados.

## Limites desta validação

A compilação PlatformIO para ESP32 exigiu baixar novamente dependências; foi interrompida devido ao espaço insuficiente no Mac. O PostgreSQL de teste também precisou ser reiniciado após falta de espaço; a suíte completa passou depois da recuperação. Nenhum ESP32 estava conectado por USB. Não houve gravação física, novo APK, migração no Supabase nem mudança de deploy/alias da API pública nesta revisão. A atualização do ambiente publicado requer aplicar a nova migração e manter API, APK e painel compatíveis conforme `docs/setup.md`.
