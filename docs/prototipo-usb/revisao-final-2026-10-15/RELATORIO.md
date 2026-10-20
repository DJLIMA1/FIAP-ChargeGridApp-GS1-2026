# Última revisão completa — 15/10/2026

**Resultado: nenhuma nova falha digital confirmada.** As correções v7, v8 e v9 estão aplicadas e coerentes no pacote preparado para o cartão. Nenhum G-code, STL, perfil, 3MF de impressão ou geometria de montagem precisou ser alterado nesta revisão.

**01CHAVE e 02TRSUP permanecem idênticos aos arquivos usados nas impressões já realizadas. Não precisam ser reimpressos por esta revisão.** A comparação usa os arquivos da v6 e o recibo da cópia efetivamente lida no cartão. O conjunto atual foi novamente verificado com as chaves e traseira superior antigas: 120 pares sem colisão, 196 posições de entrada das chaves e percurso da bandeja carregada livres. Foi incluída a espessura de 2,88 mm resultante do fatiamento das chaves.

## Conferências concluídas

| Conferência | Resultado |
|---|---|
| 31 STL individuais | Fechados, orientados corretamente, volume positivo, um corpo por peça |
| 27 peças posicionadas / 351 pares | Sem colisões volumétricas acima de 0,001 mm³ |
| 34 testes de movimento e retenção | Passaram |
| 592 verificações do roteiro do revisor independente, reexecutadas | Passaram; incluem várias posições de cada trajetória |
| 242 verificações de acessórios/reservas | Passaram |
| 39 instâncias dos 12 lotes | Correspondem aos STL individuais |
| 12 G-codes | Limites de mesa, temperaturas, extrusão, retração, suportes, início e final conferidos |
| 12 projetos 3MF | Reabertos e refatiados; perfil, geometria, quantidade e consumo conferidos |
| 81 arquivos técnicos | Permanecem idênticos aos da v9 anterior a esta revisão |
| Registros de geração/reabertura | Sem aviso ou erro do fatiador |

Os suportes estão presentes em 02, 03, 04, 05, 06, 09 e 10. A temperatura permanece 210 °C na primeira camada e 205 °C nas demais, mesa a 60 °C, PLA 1,75 mm e bico de 0,4 mm. O máximo de vazão configurado continua 6 mm³/s. Nenhuma configuração de impressão foi alterada.

## Ajuste realizado

O guia dentro do pacote completo ainda descrevia 02TRSUP como uma impressão em andamento. Atualizei esse registro para refletir sua confirmação de que **01 e 02 já foram impressos**, uniformizei as instruções e registrei esta última revisão. O conteúdo de recuperação e o pacote pronto para SD foram reempacotados e verificados; os hashes dos pacotes mudam por causa dos documentos, não por mudança nas peças.

## Continuação

Depois da cópia verificada ao SD, continuar por **CGFINAL/03TRINF7.gcode**. Na sequência: 04QDSUP, 05QDINF8, 06TAMPA, 07PTAMP, 08PTINF, 09PINO, 10BERCO9 e 11TRAVA9. 12CABO fica em OPCIONAL e depende do diâmetro dos cabos. 01/02 ficam disponíveis para recuperação, mas não precisam ser repetidos.

Os bloqueios D atuais são rígidos, retidos por duas cintas de nylon. As cintas entram pelos canais previstos e são substituídas quando cortadas na manutenção. As travas curtas flexíveis antigas não estão no lote atual. Leia a sequência ilustrada antes de instalar a bandeja.

## O que esta revisão não comprova

Não houve nova impressão ou montagem física, ensaio de força, fadiga ou medição de tolerâncias da impressora. A elasticidade dos pinos dos berços, a variante inferior da tampa, as emendas coladas e a acomodação física das cintas continuam sujeitos à montagem real. Apresente as emendas a seco antes de colar; não force encaixes. Os componentes eletrônicos finais ainda não foram definidos/medidos, e esta revisão não certifica seu encaixe ou desempenho térmico/elétrico.

**O SD não foi escrito nesta etapa.** A verificação local/ZIP não substitui a conferência de leitura após copiar e remontar o cartão.
