# Roteiro de demonstração

Prepare duas contas com senha: uma com permissão manual de operador e outra de consumidor. Neste MVP a confirmação de e-mail está desativada porque o SMTP padrão não entrega a usuários gerais. Crie previamente um posto do operador, dois pontos e um dispositivo com chave individual. Use dados fictícios e um banco exclusivo para a apresentação.

1. Abra o aplicativo como operador e mostre o posto, seus dois pontos e o estado de conexão.
2. Execute o simulador Python ou o ESP32 configurado para aquele ponto e aguarde a sincronização que o deixa online e reconciliado.
3. Entre como consumidor, encontre o posto e reserve um ponto disponível. Mostre a confirmação da reserva no próximo retorno de sincronização.
4. No app, identifique o ponto pelo código e solicite o início da recarga. O comando só aparece como confirmado após o dispositivo aplicá-lo.
5. Mostre SoC, energia e a origem `simulated` da medição no aplicativo.
6. Solicite a parada, sincronize o dispositivo e abra o histórico de consumidor e operador.
7. Inicie uma nova sessão de recarga de bancada e interrompa a rede do simulador ou da placa por mais de 45 segundos. O estado deve deixar de ser tratado como disponível por suposição e a recarga de bancada deve encerrar por segurança local pelo watchdog.

Antes do pitch, confirme o domínio HTTPS, certificado raiz no dispositivo, conexão do banco, migrações e credenciais das contas. Não apresente confirmação ou recuperação por e-mail sem SMTP próprio configurado. Faça backup/exportação do banco antes de uma migração. Não use dados bancários, chaves Pix ou contas pessoais na demonstração.

No macOS, o simulador é executado com `python3 tools/device_simulator.py --api https://sua-api` depois de definir `CHARGEGRID_DEVICE_KEY`. Em API local, HTTP é aceito apenas com `--allow-local-http` e endereço localhost. Consulte [docs/setup.md](setup.md) para os comandos completos.

## Preparar e revisar a base fictícia

1. Entre com uma conta aprovada como operador; configure `CHARGEGRID_OPERATOR_TOKEN` e `CHARGEGRID_API_URL` no ambiente do terminal, sem exibir os valores. Para carregar as variáveis do `.env` raiz em macOS/Linux, use o comando documentado em [docs/setup.md](setup.md#ferramentas-administrativas).
2. Execute `python tools/seed_demo.py --points 2` na raiz. O posto fictício e seus dois pontos serão reutilizados nas próximas execuções sequenciais.
3. Abra o posto na interface do operador e provisione o dispositivo. Use a chave mostrada uma vez para configurar o simulador conforme as instruções acima.
4. Para revisar retenção, configure `DATABASE_URL` e execute `python tools/maintenance.py`. Após revisar as contagens, `--apply` remove telemetria com mais de sete dias e limites vencidos, preservando estado de replay.
5. Dados antigos são opcionais: `python tools/import_legacy.py /caminho/privado/arquivo.json` fornece inventário sem gravar. Uma aplicação exige mapa explícito de contas confirmadas, `--source-id`, credenciais administrativas do Auth e `LEGACY_IMPORT_DATABASE_URL`; execute-a apenas fora do banco do pitch.
