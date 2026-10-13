# Plano consolidado do protótipo ChargeGrid Mini

Atualizado em 9 de outubro de 2026. O ChargeGrid Mini será um emulador físico com ESP32 WROOM próprio, API local para o painel existente, carcaça derivada do STEP original e recarga real de telefone USB-C. O teto permanece R$ 250 por unidade, sem impressão e sem o painel.

**Revisão mecânica ativa: 50% do corpo original, aproximadamente 225 × 104 × 82 mm.** O [pacote de impressão v1](prototipo-usb/ChargeGrid-Mini-50-impressao-v1.zip) contém carcaça, interiores modulares, fixações e cupons. Seguir o [guia da revisão de 50%](prototipo-usb/cad-impressao-50-v1/README.md); os arquivos já estão na escala final e devem ser importados a 100%. Verificação digital concluída; impressão e montagem física pendentes.

**Decisão mais recente do grupo: usar somente módulos prontos, sem montagem SMD ou fabricação de placa própria.** O ESP32 WROOM genérico permanece escolhido; a placa RoboCore não é requisito. TPS25810 e INA260 avulsos saíram da seleção de compra. O controle variável de capacidade é obrigatório, mas ainda não há uma combinação pronta, documentada, com envio nacional e dentro do orçamento comprovada pela pesquisa. **O usuário reafirmou que controle variável é obrigatório; a versão somente liga/desliga foi descartada como solução final.**

**Compatibilidade pretendida: qualquer celular USB-C conforme ao padrão.** A direção passa a ser recarga básica, sem depender de Quick Charge ou de um modelo específico. Estudar capacidade selecionável de 1,5/3 A em 5 V; isso não garante mudança de velocidade em todo aparelho. O usuário aceitou essa limitação para a simulação e autorizou gerar a carcaça. A [revisão de compatibilidade](prototipo-usb/compatibilidade-usb-c.md) detalha o alcance e as pendências. Nenhum módulo de potência foi fechado.

## O que já pode avançar

- [Arquivos de impressão de 50%](prototipo-usb/cad-impressao-50-v1/README.md): 35 variantes STL, oito pranchas 3MF, modelo montado e guia. Começar pela [prancha de ensaios](prototipo-usb/cad-impressao-50-v1/pranchas/00-ensaios.3mf).
- [Verificação geométrica](prototipo-usb/cad-impressao-50-v1/verificacao/relatorio.json): malhas fechadas, 97 verificações de interferência/movimento e reservas genéricas para placas. Não substitui teste físico.
- [Arquitetura mecânica anterior](prototipo-usb/arquitetura-mecanica.md) e [cupons anteriores](prototipo-usb/cad-cupons/README.md): histórico do estudo de 70%; não misturar com os encaixes da revisão atual.
- [Roteiro de montagem e validação](prototipo-usb/roteiro-de-validacao.md): ordem de montagem, medições, testes e recuperação.
- [Estudo histórico de perfis QC comutados](prototipo-usb/estudo-perfis-comutados.md): retirado da rota ativa por depender de protocolos específicos dos telefones.
- [Ofertas nacionais para a hipótese QC](prototipo-usb/ofertas-perfis-comutados.md): comparação histórica de 5/10, sem compra fechada.
- [Pesquisa de módulos prontos](prototipo-usb/pesquisa-modulos-prontos.md): placas source, ofertas verificadas e limitações de compra.
- [Pesquisa de componentes](prototipo-usb/componentes-nacionais.md): comparações nacionais e motivos de inclusão/exclusão. As cifras da placa própria foram mantidas como histórico, sem constituir orçamento atual.

## O que precisa de definição elétrica

Apenas o ESP32 WROOM está definido como família. A seleção busca módulo fonte USB-C pronto com controle documentado pelo ESP32. Os dois perfis de estudo em 5 V não implementam corrente contínua ajustável nem garantem consumo diferente em todos os celulares. O modelo exato de um telefone deixou de ser condição para escolher a arquitetura; será um dado dos ensaios. Fonte, medição e módulo USB deverão ser escolhidos como conjunto. O subtotal anterior de R$ 126,30 pertencia à rota com CIs avulsos agora excluída; não representa uma lista atual de compras. Fretes dependem do CEP, ainda não informado.

O telefone escolhe quanto consome dentro da capacidade que a fonte oferece. Um módulo ajustável de tensão/corrente, sozinho, não comprova controle de carga USB adequado. Não aplicar PWM em VBUS, reduzir tensão indiscriminadamente ou tratar fonte/sensor/relé como controle negociado de velocidade. Módulos PD trigger recebem energia de uma fonte; não substituem automaticamente o carregador que fornece energia ao celular.

A [revisão elétrica TPS25810 e INA260](prototipo-usb/revisao-eletrica.md), o [mapa de ligações](prototipo-usb/nets-plano.json) e o [contrato OpenAPI de referência](prototipo-usb/api/notas-integracao.md) conservam o estudo técnico da rota excluída. Os perfis de 1,5 A e 3 A pertencem a esse estudo; não estão aprovados para um módulo substituto. São especificações de planejamento, não circuito montado, firmware implementado ou integração concluída.

## Separação do painel e do carregador

O painel mantém seu código e suas responsabilidades de gestão. O novo equipamento terá identidade, firmware e API próprios. A integração futura passa por um adaptador explícito; a aparência não implica compatibilidade oficial GoodWe ou OCPP.

Continuam válidos os princípios do contrato: capacidades consultáveis, comandos idempotentes, confirmação física, autorização temporária, telemetria identificada e parada após falha/reset. Distinguir pedido, capacidade oferecida e medição. Energia em Wh deve vir do sensor no ponto declarado; não inflar watts para representar quilowatts. A porcentagem da bateria permanece desconhecida sem integração com o telefone.

## Casca e recuperação

O usuário definiu escala de 50%, com envelope do corpo de aproximadamente 225 × 104 × 82 mm. A revisão v1 conserva as superfícies externas principais trianguladas do STEP e adapta regiões internas. São cinco peças principais: traseira e quadro em duas partes cada, mais tampa branca inteira. As emendas usam chaves e cola; a abertura de manutenção usa quatro pinos de quarto de volta, sem parafusos. A referência de preparo é mesa de 220 × 220 mm, PETG e bico de 0,4 mm; a impressora real ainda não foi informada.

A bandeja atual mede 60 × 112 mm e recebe dois berços substituíveis. As reservas geométricas verificadas são 32 × 58 × 8 mm para ESP32 e 48 × 29 × 15 mm para potência, acima do plano de apoio. Não representam placas compradas. Plugs, fios, alturas inferiores e antena precisam ser conferidos na variante real. O inserto de cabo é bipartido, com variantes para diâmetros diferentes e presilhas de retenção separadas.

Os [volumes STEP iniciais](prototipo-usb/cad-estudo/cassette-volumes-CONCEITO.step) e a [reserva r2 de 70%](prototipo-usb/cad-referencia/README.md) permanecem como histórico. A revisão de impressão atual é baseada em malhas; não foi entregue um novo STEP paramétrico da carcaça adaptada. Preparar as peças atuais no fatiador e imprimir primeiro seus próprios cupons.

Pinos, travas, bandeja, berços e insertos são separados para facilitar recuperação sem reimprimir o corpo. Os trilhos dos berços fazem parte da bandeja substituível. Guardar parâmetros CAD, perfil do fatiador, registro de ensaio e firmware estável. Recuperar configuração não autoriza religar a porta automaticamente.

## Integridade dos arquivos

O [manifesto de hashes](prototipo-usb/integridade.json) e `prototipo-usb/verificar-arquivos.py` permitem identificar arquivos ausentes ou alterados. Eles verificam integridade dos arquivos, não substituem validação elétrica, impressão ou ensaio físico.
