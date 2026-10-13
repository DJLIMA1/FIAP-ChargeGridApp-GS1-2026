# Arquitetura mecânica modular do ChargeGrid Mini

> Atualização de 9/10/2026: a revisão mecânica ativa é a [v1 em 50%](cad-impressao-50-v1/README.md), com carcaça e interiores para impressão. Usar os cupons da [prancha 00](cad-impressao-50-v1/pranchas/00-ensaios.3mf). O texto abaixo conserva o planejamento anterior de 70% e as hipóteses elétricas ainda não implementadas; suas dimensões e encaixes não definem a revisão atual.

5 de outubro de 2026. Casca e cassete permanecem em estudo. O kit separado de cupons está disponível para impressão de teste, sem ensaio físico concluído.

## Evidência da geometria

O STEP original foi importado anteriormente e produziu `inventory.json`, `analysis.json` e `meshes.npy`. SHA-256: `dad2a7a04d5e5ee3a4910721e62fedfcc08763ce41629c49d8e0bb8d1eab153d`. Esta revisão utiliza esses dados e não altera o arquivo original. A malha foi triangulada com desvio linear de 0,35 mm e angular de 0,35 rad; portanto, ela serve à inspeção e à reserva espacial, não a cotas de fabricação de precisão.

| Elemento | Original, mm | A 70%, mm | Interpretação |
|---|---|---|---|
| Corpo, altura × largura × profundidade | 450,049 × 208,533 × 164,721 | 315,035 × 145,973 × 115,305 | Envelope externo medido |
| Tampa branca superior, A × L × P | 282,041 × 207,905 × 58,001 | 197,429 × 145,533 × 40,601 | Peça `KETI-TOP`, id 167 |
| Suporte industrial central, A × L | 264 × 156 | 184,8 × 109,2 | Referência de ocupação original, não área livre |
| PCB industrial, A × L × P | 200 × 130 × 32,2 | 140 × 91 × 22,54 | Envelope ocupado por conjunto original |

A casca não é uma caixa retangular. A largura frontal amostrada, após redução, fica perto de 103 mm na altura h=100 mm, 121 mm em h=180 mm e 145 mm em h=240 mm. A profundidade também varia. Isso torna incorreto transformar o envelope 315 × 146 × 115 mm em volume útil ou congelar uma bandeja 210 × 85 mm com base só nesses números.

Amostrei as projeções das cascas ids 60, 156 e 167 com passo de 0,5 mm na geometria original (0,35 mm na réplica). Na região central de largura 85 mm e alturas h=140..300 mm, o intervalo uniforme entre extremos de frente e trás é de aproximadamente 57,2 mm, antes das paredes. Furos, emendas e nervuras podem afetar esses extremos: **isso não é teste de contenção de sólido nem análise completa de colisões**.

A reserva inicial de 84 × 156 × 40 mm foi testada por interseção de sólidos e apresentou 109,35 mm³ de interferência com o quadro na posição proposta. A **revisão r2 usa 84 × 156 × 36 mm**, entre **h=142 e h=298 mm**, com plano traseiro em **Y=126,5 mm na geometria escalada**. Foram testadas três candidatas menores: a escolhida teve interseção nula com os nove sólidos originais e distância mínima entre superfícies de aproximadamente **1,90 mm**. O relatório em [cad-referencia](cad-referencia/README.md) registra o método e uma anomalia do algoritmo de distância em pequenos sólidos decorativos, sem removê-los da verificação.

Essa reserva não demonstra contenção numa cavidade fechada nem passagem durante a montagem. Novas paredes, placas, plugs e chicotes podem consumir a folga. A restrição de 84 mm inclui a borda estrutural e os trilhos, não apenas o PCB. O grupo exige módulos prontos; os berços finais dependem dos modelos que forem escolhidos.

## Arquitetura que permite recuperar erros

A cadeia de montagem é: **casca → sapatas universais substituíveis → cassete → trilhos/retentores substituíveis → berços específicos → placas**.

1. **Casca externa:** copiar e escalar as superfícies externas do original, manter suas curvas e divisões visuais; reconstruir o interior. A parede cresce para dentro, com 2,4 mm como parâmetro inicial. Nenhuma furação específica de ESP32, medidor ou conversor fica na casca.
2. **Interface universal da casca:** quatro alojamentos robustos, que recebem sapatas removíveis. As coordenadas e seções destes alojamentos só serão congeladas após verificar a parede e seu espaço. As sapatas absorvem ajustes de folga e desgaste; a região fixa deve trabalhar em apoio, não como lingueta flexível.
3. **Cassete:** estrutura removível única, de estudo 84 × 156 mm. Abre-se toda a frente para acessar a traseira. Libera-se uma trava substituível, desloca-se o cassete alguns milímetros e retira-se pela frente. Não depender de deslizar 156 mm dentro de uma carcaça fechada ou de passar toda a montagem pela abertura estreita da tampa branca.
4. **Trilhos e retentores:** módulos encaixam em guias universais e são presos por uma pequena peça de retenção. Os trilhos ficam substituíveis. A interface pode oferecer posições verticais indexadas para reorganizar módulos; nenhum passo deve ser congelado antes da seleção de placas.
5. **Berços:** cada placa ganha seu próprio berço. Mudou o fornecedor, a furação ou um conector? Troca-se esse berço. O projeto prevê remover individualmente cada placa sem forçar as vizinhas. Não empilhar placas sobre o módulo quente.
6. **Inserto inferior:** dividido em duas metades e removível, contém a saída de cabo, retenção e eventual entrada DC. Trocar a bitola ou o cabo exige trocar somente esse inserto. Montá-lo ao redor de um cabo pronto evita cortar o cabo para atravessar um furo pequeno.
7. **Fechamento:** ganchos rígidos recebem a carga da tampa; duas travas liberáveis apenas a retêm. As travas são peças pequenas impressas separadamente. Se uma quebrar, não se perde a casca. Sua liberação deve ser acessível pela região inferior/traseira sem alavancar a face estética.

A modularidade protege contra mudanças de placas dentro do envelope reservado. Ela não garante acomodar qualquer módulo futuro: uma placa maior, com dissipador ou cabo incompatível poderá exigir cassete e, em último caso, arquitetura diferente. Esse limite precisa ficar documentado.

## ESP32 definido pelo grupo

Usar o ESP32 WROOM de origem chinesa escolhido pelo usuário. A marca da loja não determina a capacidade funcional necessária, mas o modelo da placa determina a geometria. Retirar as cotas da placa RoboCore da seleção: o berço terá apoios ajustáveis e retenção substituível, com recorte USB específico apenas no próprio berço. Contagem e espaçamento dos pinos, largura, furos e USB serão conferidos na placa real. O volume de estudo continua genérico, sem se tornar um modelo dimensional do ESP32.

## O que medir para cada módulo antes de desenhar o berço

Datasheet de CI não substitui desenho da placa comercial. Guardar URL, SKU, revisão, foto frente/verso e unidade física de referência. Levantar:

- Contorno real do PCB, espessura e raio dos cantos.
- Alturas de componentes acima e abaixo, terminais salientes, cabeçalhos e juntas de solda.
- Centros e diâmetros dos furos em um mesmo referencial; identificar se são metalizados.
- Posição, volume e sentido de inserção dos plugs; reservar o plug conectado e o acesso dos dedos, não só a tomada soldada.
- Bordas sem componentes onde apoios e clipes podem tocar; não presumir uma faixa livre universal.
- Acesso a BOOT, RESET, ajuste de tensão, bornes e botão de destravamento.
- Zonas térmicas, dissipador, antena e exclusões elétricas.

Para PCB com furos: usar um pino de referência e outro alojamento alongado para evitar aperto por variação de impressão, mais retenção liberável. Os pinos localizam a placa, não devem expandir seus furos. Para PCB sem furo: apoiar bordas livres em três pontos e reter por clipes no berço. Não pressionar conectores, blindagem ou componentes.

Folga inferior inicial: maior saliência real de terminal/componente + margem definida no ensaio. Não fixar arbitrariamente 2 mm quando pinos de headers podem ser maiores. Preferir conectores com chave e etiquetas de função/polaridade; usar chicotes desconectáveis para remover o cassete.

## Impressão e aparência

A tampa branca tem envelope de aproximadamente 197,43 × 145,53 × 40,60 mm a 70%, cabendo geometricamente em uma mesa de 220 mm, antes de incorporar juntas, brim e suportes. Ela pode permanecer inteira. Traseira e quadro chegam a 315 mm e precisam de divisão em impressora comum de 220/256 mm.

Estudar uma divisão da traseira e do quadro na altura h=185 mm: segmentos de aproximadamente 185 e 130 mm, antes de juntas. Uma união com degrau interno e chaves rígidas removíveis mantém alinhamento; a junta deve apoiar as partes sem depender da flexão das travas. A tampa branca esconde parte da junta frontal, mas emendas laterais/traseiras ainda podem aparecer. Para aparência contínua será necessário acabamento; não prometer superfície visualmente sem emenda diretamente da impressora.

PETG é a escolha inicial para estrutura e travas. Paredes de 2,4 mm são parâmetro inicial; número de perímetros depende do bico e da largura de extrusão. Imprimir o cassete e os berços com base plana. Imprimir linguetas separadas, com sua viga no plano XY, evitando que o esforço abra camadas na raiz. Superfícies visíveis da casca precisam de orientação e suporte definidos no fatiador após o CAD final.

Foi gerado um [kit real de seis cupons](cad-cupons/README.md), com três folgas de trilho (0,25/0,35/0,45 mm por lado), macho comum, trava e receptor separados. O conjunto ocupa 94 × 81 × 8 mm. A trava usa língua de 1,2 mm, largura extrudada de 8 mm, raio de raiz de 1 mm e gancho de 0,8 mm; a deflexão nominal para liberar é 0,45 mm. O envelope de passagem foi testado com deslocamento de 0,6 mm. Esses parâmetros substituem o primeiro esboço de trava afilada; não constituem dimensionamento contra fadiga ou fluência.

Os seis sólidos e suas malhas passaram nas verificações digitais de integridade, montagem e movimento nominal. Imprimir os cupons no mesmo material/perfil da futura carcaça e registrar dez ciclos como triagem. Não confundir a passagem de um envelope rígido deslocado com uma simulação estrutural de flexão.

Fundamentação: a [Prusa](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135) recomenda considerar orientação, calibração e material na folga; não existe um valor universal. A [Protolabs Network](https://www.hubs.com/knowledge-base/how-design-snap-fit-joints-3d-printing/) orienta evitar cantos agudos, aliviar a raiz, considerar direção de impressão e reduzir esforço permanente. A [Prusa sobre PETG](https://help.prusa3d.com/article/petg_2059) descreve sua aplicação em peças mecânicas e suportes.

## Cabo, calor, rádio e manutenção

Requisito atualizado em 7/10/2026: prever cabo USB-C para USB-C completo e substituível, sem cortar condutores ou interromper CC. Reservar plug interno, curvatura e espaço para desconectar. O inserto bipartido permite instalar e retirar o cabo inteiro. Diâmetro e plug serão cotados pelo modelo recebido; não existe um envelope mecânico único para todos os cabos USB-C. Essa revisão não altera a geometria r2 nem libera a casca para impressão.

O esforço de puxar o cabo deve terminar no inserto de retenção, sem alcançar a tomada USB da placa. Uma canaleta arredondada e uma presilha removível podem reter a capa do cabo; os diâmetros e o raio de curvatura dependem do cabo real. O chicote interno terá uma pequena folga de serviço, presa longe das travas e partes quentes. Nunca contar só com atrito do plug para aliviar tração.

Colocar ESP32 no alto, com antena afastada do estágio de potência, fios e peças metálicas. A [Espressif](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/pcb-layout-design.html) recomenda pelo menos 15 mm livres ao redor da antena no produto final e teste de alcance/throughput. O berço deve poder ajustar essa posição; a própria carcaça também afeta RF. A porta de programação deve ser acessível com a frente aberta e o cassete instalado, ou após sua remoção simples; reservar o plug de serviço.

Prever entrada/saída de ar em insertos traseiros/inferiores aproveitando aberturas existentes, e espaço livre ao redor do conversor. Qualquer abertura nova que altere a aparência deve ser uma decisão explícita. Se o conjunto fechado aquecer além do aceitável, não há base para declarar que a forma externa exata funciona sem revisão: medir dissipação antes de congelar a casca. Não transferir para a réplica nenhuma classificação IP do produto original.

## Critérios para liberar CAD e fabricação

1. Congelar modelos e revisões reais de placas e conectores, incluindo fotos dimensionadas ou medições físicas.
2. Reconstruir casca em BRep com offset/espessamento válido; eliminar detalhes industriais desnecessários sem mover a superfície externa de referência.
3. Inserir volumes reais de PCB, componentes, plugs e curvaturas de cabo e testar colisões; testar também trajetórias de montagem e retirada.
4. Imprimir cupons de juntas/travas e um berço de cada família; corrigir apenas peças pequenas.
5. Conferir encaixe do cassete com gabaritos de seções da casca, antes de imprimir toda a peça.
6. Conferir fatiador: volume útil, brim, suportes, ilhas, orientação das travas e paredes mínimas.
7. Ensaiar abertura repetida, retenção de cabos, estabilidade da base e acesso à manutenção.
8. Validar temperatura e Wi-Fi com o conjunto fechado na maior carga autorizada.
9. Só então exportar STEP adaptado, STL/3MF por peça, orientação, BOM de peças impressas e instrução de montagem.

Arquivos acompanhantes: `parametros-mecanicos.json` contém parâmetros e níveis de evidência; `arquitetura-modular.png` mostra geometria real e reservas conceituais. `projected-envelope.npz` contém o mapa de projeção usado na triagem geométrica. Os STL em `cad-cupons` são exclusivamente peças de ensaio, não a casca final. A figura `arquitetura-modular.png` conserva o primeiro estudo conceitual; a reserva revisada é a r2 de 36 mm.

## Volumes de estudo inicial e revisão r2

Foi exportado `cad-estudo/cassette-volumes-CONCEITO.step`, contendo nove sólidos nomeados: base, dois trilhos, três volumes de berços e três reservas genéricas. O envelope é 84 × 156 × 40 mm, em coordenadas locais. Não há furos de placas nem juntas funcionais; os sólidos de reserva não representam componentes comprados. Esse primeiro modelo não está posicionado ou validado contra a casca original; permanece como histórico de 40 mm.

`cad-estudo/cassette-study-layout.json` permite editar posições, dimensões e cores de cada volume; `cad-estudo/create-cassette-study.py` reproduz o STEP usando OCP, sem instalar nada e sem reimportar o STEP original. Verificação: nove sólidos BRep válidos, exportação e leitura de volta bem-sucedidas, envelope confirmado. Isso confirma a integridade do arquivo, não sua fabricabilidade. A reserva de 40 mm deve incluir no estudo placas, berços, plugs e curvaturas; ainda não se demonstrou que todos esses elementos cabem.


A revisão [cassete-r2-36mm-POSICIONADO-ESTUDO.step](cad-referencia/cassete-r2-36mm-POSICIONADO-ESTUDO.step) contém os nove volumes genéricos reposicionados, com envelope total de 36 mm de profundidade. Somente a reserva genérica de potência foi reduzida de 30,6 para 26,6 mm; nenhuma placa real foi reduzida para forçar encaixe. A exportação e leitura STEP dessa revisão passaram. O arquivo nativo da casca está preservado separadamente; a tentativa de reexportar a casca complexa em STEP não passou no round trip e foi descartada.
