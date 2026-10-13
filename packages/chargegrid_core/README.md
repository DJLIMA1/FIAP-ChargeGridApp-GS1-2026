# chargegrid_core

Lógica de domínio pura (somente biblioteca padrão do Python) compartilhada entre
o aplicativo Flet (`apps/mobile`), o dashboard web (`apps/dashboard`) e a API
(`apps/api`).

Esta pasta é a **fonte única**. O app e a API recebem uma cópia idêntica gerada
por `python tools/sync_core.py`, porque o APK do Flet e a função da Vercel só
empacotam a própria pasta. Nunca edite as cópias em
`apps/mobile/src/chargegrid_core` ou `apps/api/chargegrid_core`; edite aqui e
rode o script. O teste `tools/tests/test_core_sync.py` falha se as cópias
divergirem.

Regras: sem dependências externas, sem I/O de rede ou banco, funções
determinísticas e testáveis (receba `now`/dados como argumento).
