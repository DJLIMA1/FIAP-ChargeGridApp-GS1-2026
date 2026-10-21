# Carregador GoodWe HCA G2 simulado (ESP32 DevKit + relé)

Um ESP32 DevKit com um módulo de relés faz o papel de um carregador **GoodWe HCA G2** e fala o **mesmo protocolo** do adaptador (`docs/adaptador-hca-g2.md`): Modbus TCP, mesmos registradores, mesmas escalas. O relé da **GPIO 13** liga uma tomada, e a "carga" de verdade é o carregador de um celular. A tela do ponto (painel ESP32-S3, `firmware/esp32`) é o mestre Modbus e manda no carregador.

**Cada conector é um carregador GoodWe.** Todo conector do app tem um **endereço de carregador** (1–247, único no posto, automático pela ordem: 1, 2, 3…; o dono pode trocar). **O endereço do conector é o `CG_ADDR` do ESP32 DevKit**: o carregador com `CG_ADDR 1` responde pelo conector de endereço 1 (`cg-hca-1.local`), o `CG_ADDR 2` pelo de endereço 2, e assim por diante. Enquanto nenhum carregador responde no endereço, a tela carrega com a **simulação interna** dela (como sempre fez) e o app mostra "aguardando carregador (simulação da tela)".

**Nada disso foi validado num HCA G2 real.** A potência (10015) e a energia são **SIMULADAS**: o carregador informa a potência configurada no 10029 enquanto o relé está fechado, mesmo que o celular consuma bem menos. Frase certa para a apresentação: "carregador simulado que fala o mapa Modbus V1.0.15 do HCA G2, sem validação em hardware GoodWe".

```
App/API ⇄ HTTPS (sync) ⇄ TELA (painel ESP32-S3) ⇄ Modbus TCP, Wi-Fi local, porta 502 ⇄ CARREGADOR (ESP32 DevKit) → relé GPIO13 → tomada → celular
```

| Peça | Onde |
| --- | --- |
| Firmware do carregador | `firmware/goodwe-hca-sim` (PlatformIO, `esp32dev`, Arduino-ESP32 2.0.17) |
| Regras (registradores, relé, watchdog, energia), C++ puro | `firmware/goodwe-hca-sim/lib/hca_sim_core` |
| Mapa do HCA G2 + Modbus TCP mínimo (FC03/FC06/FC16), compartilhados com a tela | `firmware/shared/hca_g2` |
| Cliente na tela (tradução dos comandos, ACK após releitura) | `firmware/esp32/src/charger_link.cpp` (puro) e `charger_modbus_esp32.cpp` (WiFiClient + mDNS) |
| Servidor de host para testar sem placa | `firmware/goodwe-hca-sim/host/hca_sim_host.cpp` |

## Material

- ESP32 DevKit (ESP32-WROOM-32, "DevKit V1"/"DOIT", placa `esp32dev`) e cabo USB de dados.
- Módulo de relés 5 V com optoacoplador (o de 4 canais serve; só o **IN1** é usado). Contatos de 10 A / 250 VCA.
- Fonte 5 V separada para as bobinas (carregador de celular de 5 V / 1 A serve).
- Para o lado da tomada: extensão ou tomada com caixa fechada, prensa-cabo e bornes isolados. Só com alguém habilitado em instalações elétricas.

## Ligação elétrica

### Baixa tensão (sinal)

| ESP32 DevKit | Módulo de relés | Observação |
| --- | --- | --- |
| GPIO 13 (D13) | IN1 | único relé configurado; ativo em LOW (padrão) |
| 3V3 | VCC (lado do sinal/opto) | com o jumper JD-VCC **retirado** |
| GND | GND (lado do sinal) | |
| — | JD-VCC e GND do lado das bobinas | **fonte 5 V separada** (+ no JD-VCC, − no GND da bobina) |

- **Alimentação do relé separada**: a bobina puxa ~70–80 mA e gera ruído no desligamento; alimentada pela USB do ESP32 costuma reiniciar a placa ou derrubar o Wi-Fi. Com o jumper JD-VCC retirado, o ESP32 só acende o LED do optoacoplador (isolamento real entre o ESP32 e a bobina).
- Módulo sem o jumper JD-VCC (sem isolamento): ligue VCC na fonte 5 V separada e o GND da fonte junto com o GND do ESP32. Nesse caso, um módulo ativo em LOW alimentado em 5 V pode não desligar com os 3,3 V do ESP32; prefira um módulo com JD-VCC.
- Módulo ativo em HIGH: `CG_RELAY_LEVEL HIGH` pelo serial (grava na NVS) ou `-D CG_RELAY_ACTIVE_LOW=0` no `platformio.ini`.
- O LED azul da placa (GPIO 2) acende junto com o relé.
- A saída é **desligada no boot, no reset e em falha**: o nível "desligado" é escrito antes de a GPIO virar saída, e o firmware nunca religa sozinho depois de reiniciar.

### Tomada (127/220 V) — aviso de segurança

> **Rede elétrica mata.** Monte o lado de 127/220 V **desligado da tomada**, dentro de uma caixa fechada, sem metal exposto, e peça a conferência de alguém habilitado. Nunca mexa com a extensão ligada. Use só para a carga do celular: o relé e os jumpers não são para um carro, aquecedor ou qualquer carga grande. Se não houver quem confira, faça a demonstração sem rede elétrica (o LED do relé e o LED azul da placa já mostram liga/desliga, ou chaveie uma carga USB de 5 V).

- Passe só a **fase** pelo relé 1: fase da rede → **COM**; **NO** (normalmente aberto) → fase da tomada. Neutro e terra vão direto da rede para a tomada.
- Use **NO**, nunca NC: sem energia no módulo, sem comando ou em falha, a tomada fica desligada.
- Prefira uma extensão com fusível/disjuntor e um circuito com DR. Prenda o cabo com prensa-cabo para não puxar os bornes.

## Gravar o firmware (feito pelo usuário, com a placa na USB)

```bash
cd firmware/goodwe-hca-sim
pio run -t upload            # compila e grava (porta detectada pelo PlatformIO; ou --upload-port /dev/cu.usbserial-XXXX)
pio device monitor -b 115200
```

Na partida aparece `[boot] goodwe-hca-sim 1.0.0: carregador GoodWe HCA G2 SIMULADO, endereco 1, rele GPIO13 ativo em LOW (ABERTO)`.

## Configurar pelo serial (115200, fim de linha `\n`)

| Comando | Efeito |
| --- | --- |
| `CG_WIFI <ssid> <senha>` | grava a rede na NVS e conecta (SSID sem espaço; com espaço use só `CG_WIFI` e responda às perguntas) |
| `CG_WIFI_CLEAR` | apaga a rede |
| `CG_ADDR <1-247>` | endereço = unit id Modbus (padrão **1**); renomeia o mDNS para `cg-hca-<n>.local`. Recusado com o relé fechado |
| `CG_STATUS` | firmware, endereço, Wi-Fi/IP, mDNS, relé, nível ativo, falha, último contato do mestre e os registradores |
| `CG_RELAY_LEVEL LOW\|HIGH` | nível ativo do módulo (NVS); a saída fica desligada |
| `CG_REBOOT`, `CG_HELP` | reinicia (relé aberto) / lista os comandos |

Exemplo de `CG_STATUS`:
```
[status] firmware=goodwe-hca-sim 1.0.0 modelo=GW7K-HCA-20 (SIMULADO) endereco=1 mdns=cg-hca-1.local
[status] wifi=conectado ssid=Loja ip=192.168.0.42 porta=502 clientes=1
[status] rele=FECHADO gpio=13 ativo_em=LOW falha=0 mestre=ha 0 s
[status] 10015=36 (3.6 kW SIMULADO) 10017=3 (carregando) 10029=36 (3.6 kW) 10032=0 10058=0 10059=1 10060=2
[status] energia_simulada_wh=12 (19001/19002)
```

Cada escrita do mestre aparece como `[SIMULADO] unit 1 reg 10029 <- 36` e cada troca do relé como `[relay] FECHADO (...)`.

## Testar do computador (sem a tela)

Computador e carregador na mesma rede. macOS resolve `.local` sozinho; no Linux é preciso o avahi (ou use o IP do `CG_STATUS`). Os endereços são os do mapa, **sem deslocamento** (registrador 10029 = endereço 10029 no pedido).

[mbpoll](https://github.com/epsilonrt/mbpoll) (`-0` = endereço do pedido, sem o +1 do padrão do mbpoll; `-t 4` = holding register; `-1` = uma vez):
```bash
mbpoll -m tcp -a 1 -0 -t 4 -r 10015 -c 3 -1 cg-hca-1.local    # 10015 potência, 10016, 10017 status
mbpoll -m tcp -a 1 -0 -t 4 -r 10029 -1 cg-hca-1.local 20      # 2,0 kW
mbpoll -m tcp -a 1 -0 -t 4 -r 10060 -1 cg-hca-1.local 2       # liga: o relé fecha
mbpoll -m tcp -a 1 -0 -t 4 -r 10060 -1 cg-hca-1.local 1       # desliga
```

pymodbus 3.x (`pip install pymodbus`; o argumento é `slave=1` até a 3.8 e `device_id=1` a partir da 3.9):
```python
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient("cg-hca-1.local", port=502); c.connect()
c.write_register(10029, 20, slave=1); c.write_register(10060, 2, slave=1)
print(c.read_holding_registers(10015, count=3, slave=1).registers)   # [20, 0, 3]
c.write_register(10060, 1, slave=1); c.close()
```

Sem nenhum comando por 15 s o relé abre sozinho (watchdog) e o status vira 5: é o comportamento esperado quando o mestre some.

Sem placa: `python tools/validate_firmware.py --hca-only` compila `tmp/panel-validation/hca_sim_host`; `hca_sim_host --port 1502 --address 1` sobe a mesma lógica em `127.0.0.1:1502` (use `-p 1502` no mbpoll ou `port=1502` no pymodbus).

## Ligar ao ponto no app

1. **O ESP32 DevKit precisa estar na mesma rede Wi-Fi da tela** (mesmo SSID e sub-rede: `CG_WIFI <ssid> <senha>` com a rede que a tela usa), com mDNS liberado. Redes de visitante com isolamento de clientes bloqueiam o Modbus e o mDNS; em outra rede a tela nunca acha o carregador e segue na simulação.
2. No app do dono: Conectores → conector mostra "Carregador GoodWe · endereço N". Grave esse número no ESP pelo serial: `CG_ADDR N` (ou troque o endereço do conector no app/painel web para o número do ESP). A API manda `connector.charger_link` (com o endereço) no sync da tela de todo conector (`docs/esp32-protocol.md`, seção "Carregador GoodWe do conector").
3. A tela resolve `cg-hca-N.local` e lê o carregador (a cada ~1 s online; a cada 5 s, com nova resolução mDNS a cada 15 s, enquanto não acha). Respondeu: o sync informa `link: online` e o app mostra "Carregador GoodWe · endereço N · online". Sem resposta: "Carregador GoodWe · endereço N · aguardando carregador (simulação da tela)".
4. Na recarga nada muda para o motorista. **No START** a tela decide o modo: carregador online → START/STOP/SET_POWER viram escritas Modbus e a tela só confirma depois de reler; offline → a recarga usa o relé/energia simulada da tela, como antes, e o sync reporta `charger.link: "offline"` com `source: "simulated"`. **A sessão termina no modo em que começou**: se o carregador aparece no meio de uma recarga simulada, ela continua simulada e só a próxima usa Modbus; se some no meio de uma recarga por Modbus, vale a parada segura abaixo.

Na tela (serial do painel): `CG_CHARGER` mostra o link (host, IP resolvido, online/offline, modo `recarga=modbus|simulacao_da_tela`, falhas, último erro) e lê os registradores na hora; `CG_CHARGER_IP 192.168.0.42` fixa o IP quando o mDNS não funciona na rede (`CG_CHARGER_IP clear` volta ao `cg-hca-<n>.local`). Com uma API antiga, sem `charger_link`, a tela continua exatamente como antes (relé/simulação interna).

## Como a tela comanda o carregador (recarga iniciada com ele online)

| Comando da API | Escritas (FC06) | ACK `applied` só quando a releitura mostra |
| --- | --- | --- |
| START | `10032 ← 0` (modo rápido, uma vez por link e só se diferente), `10029 ← limite` (só se mudou: grava flash no HCA), `10060 ← 2` | 10029 = limite, 10060 = 2, 10017 = 3 (ou 2 handshake) |
| START com limite < 1,4 kW (ou 0) | `10060 ← 1` (começa pausado) | 10060 = 1 e 10015 = 0 |
| SET_POWER ≥ 1,4 kW | `10029 ← W/100` (0,1 kW para baixo, teto 7,0 kW), `10060 ← 2` | igual ao START |
| SET_POWER < 1,4 kW | `10060 ← 1` (pausa; o 10029 fica como estava) | 10060 = 1 e 10015 = 0 |
| STOP | `10060 ← 1` | 10060 = 1 e 10015 = 0 |

- Falhas no ACK: `charger_rejected` (exceção Modbus, ex.: endereço errado → 0x0B), `charger_readback_mismatch` (escrita perdida) e, no STOP/SET_POWER, `charger_offline`. START que falha não cria sessão local e desliga o carregador se ele chegou a ligar; carregador que some exatamente no START (sem resposta) não falha: a recarga começa na simulação da tela. SET_POWER que falha mantém o limite anterior. STOP sem confirmação: a sessão termina na tela do mesmo jeito (o sync reporta `stopped`), o ACK sai `failed` e a parada é reenviada a cada leitura até confirmar.
- Leitura a cada ~1 s de 10015..10017: potência mostrada e energia integrada na tela vêm daí (SIMULADAS no carregador simulado). Uma conexão TCP só, timeouts de 400 ms (conexão) e 300 ms (resposta); ocioso e offline, tenta a cada 5 s.
- **Carregador inalcançável por 5 s durante a recarga** (inclusive pausada), em alarme (10017 = 5) ou parado sozinho por 3 leituras (reiniciou): a tela faz a parada segura local com `end_reason: "device_fault"` e sincroniza na hora. Do outro lado, o watchdog do carregador abre o relé em 15 s sem contato.
- Carregador ligado sem recarga na tela (a tela reiniciou, outro mestre): a leitura periódica escreve `10060 ← 1`.

## Registradores do simulado

Holding registers, FC03 leitura, FC06/FC16 escrita, unit id = endereço (padrão 1; o HCA real usa 247 segundo a comunidade).

| Endereço | Uso no simulado |
| --- | --- |
| 10029 | 0..70 (0,1 kW). Acima de 70 → exceção 03. Abaixo de 14 é aceito e **pausa** (extensão do simulado; a tela nunca escreve abaixo de 14) |
| 10060 | 1 desliga, 2 liga; outro valor → exceção 03. Volta a 1 no boot e no watchdog |
| 10032 | 0..2 (a tela escreve 0). 10029 e 10032 ficam na NVS, como na flash do HCA |
| 10015 | SIMULADO: = 10029 com o relé fechado, 0 aberto |
| 10017 | 1 parado/pausado, 3 carregando (relé fechado), 5 alarme (watchdog). Códigos do mapa: 0 livre, 1 plugado, 2 handshake, 3 carregando, 4 concluído, 5 alarme, 8 falha ao iniciar |
| 10058 / 10059 | 0 (7 kW) / 1 (monofásico): GW7K-HCA-20 |
| 10000, 10019–10039 | graváveis sem efeito (como `tools/edge/modbus_sim.py`); 10015/10017/10058/10059 são só leitura (exceção 02) |
| 19000–19006 | **extensão SIMULADA, fora do mapa oficial** (nenhum HCA real responde): 19000 versão (1), 19001/19002 energia desde o boot em Wh (U32, palavra alta primeiro), 19003 relé, 19004 falha (1 = watchdog), 19005 endereço, 19006 sempre 1 (simulado) |

Regras do relé: fecha só com 10060 = 2, 10029 ≥ 14 e sem falha; abre com 10060 = 1, 10029 < 14, watchdog (15 s sem nenhuma leitura ou escrita do mestre), reset e boot. Depois do watchdog o 10060 fica em 1 e o status em 5 até a próxima escrita do mestre; o relé só fecha de novo com um novo `10060 ← 2`. A energia soma a potência simulada só com o relé fechado e para no instante do watchdog.

**Biblioteca Modbus:** implementação mínima própria (FC03/FC06/FC16, ~150 linhas em `firmware/shared/hca_g2/src/modbus_tcp.cpp`) em vez de emelianov/modbus-esp8266 ou eModbus: o mesmo código serve o carregador e a tela, roda no host (testes com sanitizers e servidor real em `127.0.0.1`), não aloca memória, deixa o watchdog e o unit id sob controle da lógica testada e não depende da compatibilidade das bibliotecas com os dois cores usados (Arduino-ESP32 2.0.17 no carregador, 3.x no painel).

## Testes

```bash
python tools/validate_firmware.py --hca-only                      # lógica do carregador + link da tela (C++, sanitizers)
python tools/validate_firmware.py --compare-panel <frames-antigos> # tudo, inclusive o controlador real (Modbus e simulação)
python -m pytest -q tools/tests/test_hca_sim_e2e.py               # Modbus TCP de verdade contra o servidor de host
cd firmware/goodwe-hca-sim && pio run                             # compila o firmware (não grava)
```

## Pendências de hardware

- Validar na bancada: nível do módulo de relés com 3,3 V, ruído da bobina com a fonte separada, alcance do Wi-Fi, resolução `cg-hca-1.local` pela tela na rede da loja.
- Nada aqui substitui a validação num HCA G2 real: unit id 247, comportamento do 10017 com carro, instabilidade relatada da conexão Modbus TCP no equipamento real e a conversão potência → corrente continuam como em `docs/adaptador-hca-g2.md`.
