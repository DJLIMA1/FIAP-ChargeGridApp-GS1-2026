# Roteiro de demonstração

## Experiência de escolha e confirmação

Mensagem principal: **ChargeGrid — Recarga com confirmação, do app ao ponto.**

Na home, a ação contextual aparece antes do mapa: começar uma busca, consultar a reserva ou acompanhar a sessão existente. Na busca, abra **Comparar por conector, preço e tempo** para escolher o conector, limitar a tarifa ou mostrar apenas pontos disponíveis. A ordenação por proximidade depende do endereço/coordenadas da busca e informa distância em linha reta.

Em **Minha intenção**, escolha um valor em reais ou minutos para comparar estimativas pela potência nominal. O plano acompanha a seleção até o wizard, inclusive ao reservar e depois confirmar a chegada na mesma sessão. Pontos gratuitos usam limite de tempo. O valor não é pagamento, e potência nominal não é garantia de energia entregue. As estimativas anteriores a cupons usam o mesmo cálculo da revisão.

Antes de um novo pedido de início, as condições do ponto são consultadas novamente. Se tarifa, potência ou limite mudarem, o app pede outra revisão. Se a resposta de um pedido anterior foi perdida, o app repete o pedido original de forma idempotente; não cria uma nova recarga com condições diferentes.

A reserva e a recarga mostram a confirmação e os horários realmente disponíveis no serviço. Em consultas bem-sucedidas, não há faixa permanente de atualização. Se a atualização falhar, uma faixa informa que os dados são os últimos conhecidos e oferece nova tentativa. O horário da última consulta do app é distinto da última medição do dispositivo; a faixa não transforma o estado antigo em disponibilidade confirmada.

Roteiro curto: comparar → escolher → reservar → confirmar chegada → revisar limites → solicitar início → acompanhar confirmação → solicitar parada → conferir encerramento. A falha física de comunicação deve ser demonstrada somente no ensaio integrado descrito abaixo; a conta demo permanece isolada.

## Conta demo dentro do aplicativo

Na prévia local de desenvolvimento, selecione **Entrar na conta demo**. Também é possível entrar com `demo@chargegrid.example` e senha pública `demo1234`. Essa identidade é reconhecida pelo próprio aplicativo: não precisa criar usuário no Supabase. A demo exige `CHARGEGRID_ENABLE_DEMO=1`; o script de prévia define essa opção. Sem ela, o botão, as credenciais na tela e o login demo ficam indisponíveis. O APK de produção deve ser criado sem essa variável.

Postos, pontos, cupons, perfil, reservas e recargas dessa conta são simulados em memória. A demo começa no modo motorista; em **Conta → Usar como operador**, gerencie os postos ou adicione um equipamento simulado. Use o código `#F12345` para experimentar a recarga. O progresso segue o relógio da simulação e respeita os limites selecionados. No início, o mapa usa um recorte geográfico local da Praça da Sé (© OpenStreetMap contributors), com o posto de exemplo identificado. Outros locais usam uma visão esquemática explícita; a busca reconhece os locais de exemplo. Não há consulta externa de mapa/endereço durante a demo.

Os dados são reiniciados ao sair, reconectar ou entrar novamente. Perfil e tema da demo não alteram preferências persistidas de uma conta real. Os avisos de demonstração aparecem nos fluxos; não há pagamento, telemetria física ou comando enviado ao ESP32.

Para iniciar, siga uma etapa por vez: **Confirmar ponto → Definir limites → Revisar recarga**. O botão **Solicitar início** aparece somente na revisão. É possível voltar para editar sem perder os campos. Por valor define um teto de custo estimado e mantém um tempo máximo de segurança; não gera pagamento.

Na etapa Definir limites, “Ajustar tempo máximo” mostra a duração de segurança e expande o campo alinhado ao cartão. “Cupom de desconto” é opcional e mantém o código ao recolher o cartão; a validade e o desconto só são confirmados pela API ao solicitar o início.

A aba **Chat** reúne as orientações antes disponíveis em Ajuda e consulta a última recarga, recarga atual ou reserva da conta. As respostas são automáticas locais, não atendimento humano nem uma IA externa. A conversa e o rascunho existem somente nesta sessão e são apagados ao sair. A tela **Conta** mostra os dados; use **Editar informações** para alterá-los.

Para abrir a prévia web local:

```sh
PYTHONPATH=apps/mobile/src .venv/bin/python tools/preview_mobile_flows.py
```

Abra `http://127.0.0.1:8855` e entre na conta demo. A prévia usa a navegação normal do aplicativo, sem seletor de cenários.

## Demonstração integrada com API e dispositivo

Prepare duas contas com senha: uma de vendedor e outra de consumidor. Neste MVP a confirmação de e-mail está desativada porque o SMTP padrão não entrega a usuários gerais. Provisione dois equipamentos fictícios pela ferramenta administrativa, configure cada chave no dispositivo correspondente e vincule seus QRs na conta do vendedor. Use dados fictícios e um banco exclusivo para a apresentação.

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

1. Em um banco exclusivo de demonstração, execute `tools/provision_point.py` para cada equipamento conforme [o guia de fábrica](setup.md#provisionar-e-vincular-um-equipamento). Mantenha JSON e QR privados; a chave de comunicação é diferente do segredo de propriedade.
2. Entre como vendedor, escaneie o primeiro QR e configure/ative o posto e ponto resultantes. Vincule o segundo QR ao mesmo posto e revise/ative esse segundo ponto. Não há aprovação manual nem criação de ponto por formulário.
3. Configure o simulador com a chave individual entregue pela fábrica. `python tools/seed_demo.py` é opcional: cria/reutiliza apenas um agrupamento chamado `ChargeGrid Demo FIAP`, nunca equipamentos. A ferramenta usa `CHARGEGRID_OPERATOR_TOKEN` de vendedor já habilitado e `CHARGEGRID_API_URL`, sem imprimir os valores.
4. Para revisar retenção, configure `DATABASE_URL` e execute `python tools/maintenance.py`. Após revisar as contagens, `--apply` remove telemetria com mais de sete dias e limites vencidos, preservando estado de replay.
5. Dados antigos são opcionais: `python tools/import_legacy.py /caminho/privado/arquivo.json` fornece inventário sem gravar. Uma aplicação exige mapa explícito de contas confirmadas, `--source-id`, credenciais administrativas do Auth e `LEGACY_IMPORT_DATABASE_URL`; execute-a apenas fora do banco do pitch.

## Seleção de postos e presença

Na lista, escolha “Ver pontos” no posto desejado. O detalhe mostra separadamente cada equipamento, tarifa, potência e tempo máximo. “Já estou aqui: iniciar” abre a confirmação de presença; o #F deve ser lido na tela do equipamento naquele momento, pois é rotativo. Não existe atalho “Tenho o código #F” para reutilizar um código guardado. Na conta demo, o código de teste continua disponível somente na etapa de confirmação.
