# Mobile 0.2.3 — seletor deslizante e validação animada

21/09/2026 · Android build 13. Consolida as animações da versão 0.2.2 e a remoção do efeito de onda no seletor.

- O fundo vermelho desliza entre consumidor e vendedor em 280 ms, proporcional à largura de cada opção. Trocar o tipo não reconstrói os campos; seleção fica bloqueada durante o envio.
- O seletor não usa ripple: somente a faixa vermelha desliza, sem a onda branca sobre os rótulos. A correção foi conferida no navegador e aprovada pelo usuário.
- Dados inválidos na autenticação recebem um balanço horizontal curto, borda de erro e mensagem abaixo do campo. Editar remove o aviso. Erros de senha fraca retornados pelo servidor também destacam a senha, sem apagar seu conteúdo.
- Mensagens possuem anúncio acessível e vermelho de maior contraste no tema escuro. Redução de movimento mantém mensagens/bordas, mas elimina o deslocamento e torna o seletor instantâneo.
- A animação retorna ao centro mesmo se cancelada, sem atualizar uma tela já encerrada.

Validação: **88 testes mobile aprovados**, Ruff limpo a partir da raiz e de `apps/mobile`, build Android e assinatura verificados. A configuração de imports do Ruff agora é explícita para evitar diferença entre execução local e CI; a CI da publicação anterior havia falhado nessa classificação de imports.

Navegador real: cadastro, deslize para vendedor, campo obrigatório vazio, erro de e-mail no login, limpeza do aviso ao editar e preservação do texto. Nenhuma nova conta foi criada nesse teste. Validação nativa em aparelho Android continua pendente.

Artefato local: `builds/chargegrid-0.2.3.apk`. Os módulos de autenticação, movimento e tema empacotados foram comparados com o código atual; sem `.env` nem testes no APK.

SHA-256: `293101b530b64420de412f6516c57417b869f12fd495ef9a01f99fff0628589c`.
