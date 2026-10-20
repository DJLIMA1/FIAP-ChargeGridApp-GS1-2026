# Estratégia para vencer — ChargeGrid FFIVE

20/10/2026. Baseado na [análise dos pitches](analise-pitches-goodwe-fiap-2026.md), na [análise dos concorrentes no GitHub](analise-concorrentes-github-2026.md), no [planejamento por frentes](planejamento-features/README.md) e no estado atual do código (`main`, app 0.6.8).

## A tese

Cada concorrente forte resolveu **uma ou duas** partes do problema:

| Concorrente | O que tem de melhor | O que não tem |
| --- | --- | --- |
| EMPS (1CCA) | Otimização MILP, previsão com métrica, Stripe teste | Equipamento funcionando, dados reais, OCPP/Modbus |
| Smart Charge (1CCA) | Pagamento Asaas, leilão de potência, fidelidade | App nativo, equipamento além de Arduino via USB |
| ChargeGrid 1CCPG | Melhor venda e demo de causa e efeito | Código que sustente a demo |
| STIG4 (1CCR) | Engenharia, ~1.190 testes, produção | Qualquer hardware |
| ChargeOps (1CCPK) | Medição física real | Deploy, foco comercial, pitch |

Nenhum deles tem uma **recarga inteira acontecendo de verdade na frente da banca**: pagar → o equipamento confirma → a potência muda sozinha quando outro carro entra → o recibo bate com o que aconteceu. Nós já temos a parte mais difícil (app instalado, painel ESP32 que confirma comandos, API em produção, preço dinâmico). Faltam duas peças que todos os líderes têm: **pagamento** e **rebalanceamento ao vivo**.

**Frase de posicionamento:** *"Os outros mostram uma simulação. O ChargeGrid mostra uma recarga confirmada pelo equipamento, do pagamento ao recibo."*

A meta não é ter mais telas que o EMPS ou a STIG4. É ser **a única equipe sem buraco**: comercial (pagamento, preço, margem), energético (demanda), físico (equipamento) e de confiança (tudo confirmado e explicável).

## Prioridades

A data da final não está confirmada. O README da ChargeOps cita apresentação no NEXT em **22/10**. Se for isso, só a camada **P0** cabe, e a camada **D** (demo e ensaio) vale mais que qualquer feature nova.

### P0 — fechar os dois buracos que a banca já apontou

**1. Pagamento real em sandbox (Pix primeiro).**
- Provedor: **Mercado Pago** (Pix sandbox simples, sem empresa, SDK Python) ou Asaas. Stripe só se Pix der problema.
- Fluxo: o motorista aceita o orçamento → a API cria a cobrança com o **teto** como valor → o **webhook** confirma → só então a API manda `START` → no fim, a energia medida define o valor e a **diferença volta como crédito**. O crédito de sobra já existe simulado no fluxo de bateria cheia; trocar a origem do dinheiro, não o fluxo.
- **Diferencial que ninguém tem:** o **QR do Pix aparece também no painel físico**. Quem chega sem o app paga no próprio equipamento. Isso responde ao "caixa sem app" do EMPS e ao totem do Smart Charge, com hardware de verdade.
- Estados próprios e visíveis: `aguardando pagamento`, `pago (sandbox)`, `recusado`, `expirado`, `devolvido`. Ambiente sempre rotulado como sandbox.
- Aceite: um pagamento de teste confirmado pelo webhook libera a recarga; sem webhook, nada liga; a devolução aparece no recibo.

**2. Rebalanceamento ao vivo, confirmado pelo equipamento.**
- A regra já existe em `packages/chargegrid_core/chargegrid_core/power.py`: divisão proporcional, piso de 1,4 kW, soma ≤ teto. Hoje ela vale só no início da recarga.
- Recalcular a divisão em cada evento: sessão começa, sessão termina, bateria cheia, mudança do teto, **mudança do consumo da loja**.
- Novo comando de protocolo `SET_POWER` (aditivo; firmware antigo ignora), com ACK `applied`. **Regra de segurança:** reduzir primeiro, esperar a confirmação, só depois aumentar outro ponto. A soma nunca passa do limite nem durante a transição. É isso que separa o nosso de quem só faz conta.
- **Consumo da loja simulado** no painel web (controle deslizante "carga do estabelecimento"), o mesmo artifício que deu a vitória de demo à 1CCPG, só que aqui a potência muda **no painel físico**.
- **Registro da decisão:** "Seu carro recebeu 7,2 kW porque a loja está usando 38 kW de 60 kW e há 2 carros carregando". Aparece no app, no painel do vendedor e no recibo.
- Aceite: com 3 pontos (1 físico + 2 simulados), elevar a carga da loja reduz todos, a soma nunca passa do limite, e o painel físico mostra o novo valor depois do ACK.

### P1 — diferenciais que nenhum concorrente demonstrou

**3. Recibo explicável e conciliado.** Uma tela e um PDF que juntam tudo: preço aceito (base, ajuste por demanda, cupom), energia **confirmada pelo equipamento**, gráfico de potência ao longo do tempo com os motivos das mudanças, pagamento (valor pago, consumido, devolvido) e o identificador do provedor. Junta preço, demanda e pagamento numa coisa só, e é a melhor resposta à pergunta "como vocês cobram?".

**4. Falha e recuperação ao vivo.** Desligar o Wi-Fi do painel no meio da recarga: o equipamento aplica a política local (continua dentro dos limites ou para), o app mostra "sem comunicação, aguardando confirmação", e ao religar a sessão se reconcilia sem cobrar energia inventada. Já temos a base (ACK, parada local, recuperação de sessão). **Nenhuma equipe mostrou isso.** São 30 segundos de demo que provam confiabilidade.

**5. Resultado para o dono do posto.** No painel do vendedor: receita, custo estimado da energia, comissão da plataforma e **margem por sessão**, com o efeito do preço dinâmico e dos cupons. Exportar CSV e PDF. Responde à pergunta de rentabilidade que a banca fez ao Hub e a nós, e corrige o erro do pitch (receita bruta ≠ lucro).

**6. Taxa de permanência (overstay).** Quando a bateria enche e o carro continua conectado: aviso no app, 10–15 min de tolerância e depois uma taxa por minuto, aceita no orçamento. A parada por bateria cheia já existe, então o custo é baixo. Tira o único diferencial da ElectroBrain e iguala EMPS e vencedoresdonext.

### P2 — só se P0 e P1 estiverem prontos e ensaiados

**7. Adaptador com o mapa de registradores do HCA G2.** Driver "GoodWe HCA G2" com os registradores Modbus documentados (10024, 10025, 10026, 10029, 10032), com transporte simulado. Não liga em nada real, mas mostra o caminho para o equipamento GoodWe. Custo baixo e muita credibilidade com a GoodWe. **Deixar explícito que é simulado.**

**8. Previsão com número.** Um estimador simples de ocupação por hora (média do mesmo dia e hora, suavizada) comparado a um baseline ingênuo, com erro medido fora dos dados de ajuste. Usar para "melhor horário para carregar barato" no app. Não precisa vencer o MILP do EMPS; precisa ter **metodologia e métrica** para responder à banca.

**9. MCP público** (do planejamento 08). É interessante tecnicamente, mas a banca nunca valorizou isso. Fica por último.

### Não fazer agora

RFID, carteira completa com saldo e extrato, separação solar/rede real, ML pesado, mais telas no app, fidelidade em níveis. Todos geram trabalho e risco sem fechar nenhuma pergunta da banca.

## Direções de projeto

1. **Uma fonte de verdade para cada fato.** Preço aceito, potência aplicada, energia medida e pagamento confirmado são registros distintos, e app, painel físico, painel web e recibo leem os mesmos. Se dois lugares mostrarem números diferentes na demo, perdemos o argumento de confiança.
2. **Nada é "feito" sem confirmação.** Vale para potência (ACK do `SET_POWER`), pagamento (webhook) e parada (ACK do `STOP`). É o nosso padrão e é o que os concorrentes não têm.
3. **Rótulo honesto em tudo que é simulado.** Energia simulada, carga da loja simulada, pagamento sandbox. Os concorrentes fortes documentam isso com cuidado; se a banca pegar um exagero nosso, a vantagem de credibilidade some.
4. **Mudanças aditivas no protocolo do ESP32.** Firmware antigo continua funcionando. Gravar o firmware novo no painel cedo e manter o anterior pronto para regravar.
5. **Congelar features antes da apresentação.** Depois do congelamento: só correções, ensaio e plano B.

## Camada D — demonstração e pitch (vale mais que qualquer feature)

**Roteiro de 4 minutos:**

| Tempo | O que mostrar |
| --- | --- |
| 0:00–0:30 | A dor do lojista em uma frase e o **painel físico já na tela**. A ChargeOps perdeu porque o hardware apareceu depois do tempo. |
| 0:30–1:30 | Motorista escolhe o posto, vê o preço com o motivo, paga Pix (sandbox), **o painel físico confirma e liga**. |
| 1:30–2:30 | Segundo carro entra e a loja aumenta o consumo: **a potência do painel cai sozinha**, com o motivo na tela, e a soma fica abaixo do limite. |
| 2:30–3:00 | Wi-Fi desligado e religado: a sessão se reconcilia. |
| 3:00–3:40 | Fim: recibo com energia confirmada, valor devolvido e margem do dono no painel web. |
| 3:40–4:00 | O caminho para o HCA G2 e o modelo de receita **corrigido** (receita bruta ≠ lucro). |

**Respostas prontas, com números, para as perguntas que a banca repetiu:**
- *Como vocês gerenciam a demanda?* Regra, limite, exemplo numérico e ACK antes de aumentar.
- *Como cobram?* Teto pré-pago, energia confirmada, devolução e o recibo.
- *Como é a tarifa?* Base + ajuste por ocupação, fila e pico, travada no aceite.
- *É rentável para o lojista?* Margem por sessão com os números do painel.
- *O que é real e o que é simulado?* Responder antes de perguntarem.

**Segurança contra falha na demo:**
- Checklist uma hora antes: API respondendo, alias da Vercel apontando para o último deploy, painel no Wi-Fi certo, APK atualizado no celular, conta de demonstração com dados limpos, webhook sandbox testado.
- **Vídeo gravado da jornada inteira** como plano B, pronto para tocar se a rede cair.
- Celular com 4G como roteador reserva para o painel.
- Ensaiar com cronômetro pelo menos três vezes e com alguém fazendo as perguntas da banca.
- Nunca citar `chargegrid-api.vercel.app`: esse domínio é de outra equipe.

## Como cada concorrente perde para nós depois disso

| Concorrente | O argumento contra |
| --- | --- |
| EMPS | Otimizam no papel com dados sintéticos; nós mostramos o equipamento reduzindo a potência e confirmando. |
| Smart Charge | Equipamento é Arduino via USB; o nosso é um painel conectado que confirma cada comando e recebe Pix na tela. |
| ChargeGrid 1CCPG | Demo de causa e efeito igual à deles, mas com hardware e com o código sustentando. |
| STIG4 | Software excelente, mas nada físico; a GoodWe vende equipamento. |
| ChargeOps | Medem energia de verdade, mas é condomínio e sem deploy; nós somos o eletroposto comercial completo e publicado. |
