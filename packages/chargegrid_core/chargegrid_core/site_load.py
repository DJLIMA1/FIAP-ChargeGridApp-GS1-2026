"""Consumo SIMULADO do estabelecimento que recebe o eletroposto (sem medidor real).

Regra pura, sem banco nem rede, usada pela API, pela conta demo e pelos testes. O
rebalanceamento (``balancing``) desconta este consumo do limite contratado sempre que
não há medição real nem um valor enviado pelo simulador/demonstração.

Modelo
------
``consumo = pico(tipo, porte) × curva_horária(tipo, dia) × estação × dia × ruído``

* **Curva horária** por tipo de estabelecimento (fração do pico, hora local de Brasília,
  UTC−3), com dia útil, sábado e domingo; interpolada linearmente entre as horas.
* **Estação**: o ar-condicionado pesa mais no verão (pico em fevereiro); a fração de
  climatização de cada tipo define quanto o consumo cai no inverno.
* **Dia**: ±4 % por dia (dia mais quente ou mais frio), reproduzível por posto e data e
  interpolado entre os dias (sem salto à meia-noite).
* **Ruído suave**: duas oitavas de ruído de valor (30 min e 2 h, interpolação cosseno),
  semeadas pelo posto: o mesmo posto na mesma janela dá sempre o mesmo valor.
* **Janela**: o valor é constante em janelas de 5 min (``WINDOW_SECONDS``). Assim a
  decisão do posto muda no máximo a cada 5 min por causa da loja, e cada passo é pequeno.
* **Teto**: o consumo simulado nunca passa de ``MAX_LOAD_SHARE`` (85 %) do limite
  contratado, então sempre sobra potência para ao menos um carro; a soma loja +
  carregadores continua limitada pelo ``balancing`` (disponível = limite − loja).

Números de referência (ordem de grandeza; ver ``SOURCES``)
-----------------------------------------------------------
* Loja de conveniência: ~173 MWh/ano, pico médio de 20 kW, refrigeração 59–64 % e
  ar-condicionado 26–28 % do consumo (estudo com 9 lojas, TNI Journal); intensidade de
  ~53 kWh/ft²·ano (~570 kWh/m²·ano) em "food sales" no CBECS 2018 (EIA), 74 % delas lojas de
  conveniência. Operação 24 h: base alta (refrigeração) e pico à tarde (calor + movimento).
* Supermercado: refrigeração de 74–82 % (benchmark UFV, médio porte) a "até 70 %" (ABRAS):
  base noturna alta; ~1.000 m² × ~570 kWh/m²·ano ≈ 570 MWh/ano (média ~65 kW, pico ~100 kW).
* Padaria: padaria-modelo do Sebrae/ITPC com ~212 MWh/ano (média ~24 kW), forno ~29 % e
  refrigeradores/freezers ~31 %: picos de forno de madrugada/manhã e no meio da tarde.
* Restaurante: CBECS 2018 "food service" ~44 kWh/ft²·ano (~470 kWh/m²·ano): ~250 m² ≈
  120 MWh/ano (média ~13 kW), picos no almoço e no jantar.
* Farmácia: sem estudo setorial público; estimativa por inventário (climatização 40–50 % do
  consumo de um prédio comercial, iluminação, poucos refrigeradores): pico ~12 kW.
* Shopping: iluminação ~15 W/m² + 25 % de outros usos (PUC-Rio) e climatização 40–50 % do
  consumo (UTFPR): ~20.000 m² → pico ~750 kW; abre 10–22 h (domingo 14–20 h).
* Comércio em geral: pico diurno puxado pelo ar-condicionado (UFSC; recorde do SIN às
  14h20, ONS) e queda depois das 18 h.

Limite contratado padrão (quando o dono não informou)
-----------------------------------------------------
Pela REN ANEEL 1.000/2021 (art. 23), unidade em baixa tensão (Grupo B) tem carga instalada
de até 75 kW; acima disso o atendimento é em média tensão (Grupo A), com demanda contratada.
Padrão: ``max(75 kW, pico simulado × 1,3)`` arredondado para cima de 10 em 10 kW — o teto
do Grupo B para comércio pequeno e, para quem já é Grupo A, uma demanda contratada com folga
de 30 % sobre o pico (ultrapassar a demanda contratada além da tolerância de 5 % é cobrado
com tarifa de ultrapassagem).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal

LABEL = 'SIMULADO'
LOCAL_TZ = timezone(timedelta(hours=-3), 'America/Sao_Paulo')  # Brasil sem horário de verão desde 2019
WINDOW_SECONDS = 300
MAX_LOAD_SHARE = Decimal('0.85')
GROUP_B_LIMIT_KW = Decimal(75)
LIMIT_MARGIN = Decimal('1.3')
LIMIT_STEP_KW = Decimal(10)
SEASON_DEPTH = 0.35   # fração da climatização que some no inverno
DAY_SWING = 0.04      # ±4 % por dia
NOISE = ((1800, 0.05), (7200, 0.03))  # (período em s, amplitude): 30 min ±5 %, 2 h ±3 %
STEP = Decimal('0.1')

SOURCES = (
    ('TNI Journal (2019), Investigation of Energy Conservation Potential for Convenience Stores in Thailand: '
     'https://ph01.tci-thaijo.org/index.php/TNIJournal/article/view/210286'),
    ('EIA CBECS 2018, tabela C14 (intensidade elétrica por atividade): '
     'https://www.eia.gov/consumption/commercial/data/2018/ce/pdf/c14.pdf'),
    'EIA CBECS, perfil "food sales": https://www.eia.gov/consumption/commercial/pba/food-sales.php',
    'UFV, Benchmark energético para supermercados de médio porte: https://locus.ufv.br//handle/123456789/31349',
    ('Sebrae, Eficiência energética e conformidade de fornos elétricos (padaria-modelo ITPC): '
     'https://sebrae.com.br/Sebrae/Portal%20Sebrae/Arquivos/Efici%C3%AAncia%20Energ%C3%A9tica%20e%20conformidade'
     '%20de%20fornos%20el%C3%A9tricos%20(1).pdf'),
    ('PUC-Rio, dissertação sobre consumo de shoppings (iluminação 15 W/m² + 25 %): '
     'https://www.maxwell.vrac.puc-rio.br/55812/55812_4.PDF'),
    ('UTFPR, climatização 40–50 % do consumo de edifícios comerciais: '
     'https://riut.utfpr.edu.br/jspui/bitstream/1/16923/1/PG_DAELE_2013_2_10.pdf'),
    ('CBENS/UFSC, pico diurno comercial pelo ar-condicionado: '
     'https://anaiscbens.emnuvens.com.br/cbens/article/download/2274/2261/2260'),
    ('ANEEL REN 1.000/2021 (Grupo B até 75 kW de carga instalada): '
     'https://www.rge-rs.com.br/sites/rge-rs/files/2022-04/REN%201000_2021.pdf'),
)


@dataclass(frozen=True)
class Profile:
    """Tipo de estabelecimento: pico típico (porte médio, verão), curvas e fração de climatização."""

    label: str
    peak_kw: Decimal
    weekday: tuple
    saturday: tuple
    sunday: tuple | None = None
    sunday_factor: float = 1.0
    ac_share: float = 0.3
    hours: str = ''


# Frações do pico por hora local (0h … 23h).
PROFILES = {
    # Loja de conveniência: em geral a de um posto de combustível (24 h).
    'conveniencia': Profile(
        'Loja de conveniência', Decimal(22),
        (0.66, 0.64, 0.63, 0.62, 0.62, 0.64, 0.70, 0.76, 0.80, 0.84, 0.88, 0.92,
         0.95, 0.97, 1.00, 1.00, 0.98, 0.95, 0.92, 0.88, 0.82, 0.77, 0.72, 0.69),
        (0.68, 0.66, 0.64, 0.63, 0.62, 0.63, 0.66, 0.71, 0.77, 0.83, 0.88, 0.93,
         0.96, 0.98, 1.00, 0.99, 0.97, 0.94, 0.91, 0.88, 0.84, 0.80, 0.75, 0.71),
        sunday_factor=0.97, ac_share=0.27, hours='24 h'),
    'farmacia': Profile(
        'Farmácia', Decimal(12),
        (0.22, 0.21, 0.21, 0.21, 0.21, 0.22, 0.30, 0.55, 0.75, 0.85, 0.90, 0.94,
         0.96, 0.98, 1.00, 1.00, 0.97, 0.93, 0.88, 0.82, 0.75, 0.62, 0.40, 0.26),
        (0.22, 0.21, 0.21, 0.21, 0.21, 0.22, 0.28, 0.48, 0.68, 0.80, 0.86, 0.90,
         0.92, 0.93, 0.94, 0.92, 0.88, 0.84, 0.78, 0.72, 0.64, 0.52, 0.36, 0.25),
        sunday_factor=0.85, ac_share=0.45, hours='7–23 h'),
    'padaria': Profile(
        'Padaria', Decimal(45),
        (0.30, 0.30, 0.30, 0.32, 0.60, 0.88, 1.00, 0.95, 0.80, 0.70, 0.68, 0.72,
         0.75, 0.70, 0.66, 0.78, 0.86, 0.82, 0.72, 0.62, 0.52, 0.40, 0.32, 0.30),
        (0.30, 0.30, 0.30, 0.33, 0.62, 0.92, 1.00, 1.00, 0.88, 0.76, 0.72, 0.74,
         0.74, 0.68, 0.62, 0.70, 0.78, 0.76, 0.68, 0.58, 0.48, 0.38, 0.32, 0.30),
        sunday_factor=0.95, ac_share=0.15, hours='6–21 h, fornos de madrugada'),
    'supermercado': Profile(
        'Supermercado', Decimal(100),
        (0.58, 0.57, 0.56, 0.56, 0.56, 0.57, 0.63, 0.75, 0.84, 0.89, 0.93, 0.96,
         0.97, 0.98, 1.00, 1.00, 0.98, 0.97, 0.96, 0.93, 0.88, 0.80, 0.68, 0.61),
        (0.58, 0.57, 0.56, 0.56, 0.56, 0.57, 0.62, 0.74, 0.85, 0.92, 0.96, 0.99,
         1.00, 1.00, 1.00, 0.99, 0.97, 0.95, 0.92, 0.88, 0.82, 0.74, 0.65, 0.60),
        sunday_factor=0.88, ac_share=0.2, hours='7–22 h, refrigeração 24 h'),
    'restaurante': Profile(
        'Restaurante', Decimal(30),
        (0.18, 0.17, 0.17, 0.17, 0.17, 0.18, 0.22, 0.30, 0.42, 0.58, 0.80, 0.97,
         1.00, 0.90, 0.62, 0.48, 0.46, 0.55, 0.75, 0.90, 0.92, 0.80, 0.52, 0.28),
        (0.22, 0.18, 0.17, 0.17, 0.17, 0.17, 0.20, 0.26, 0.36, 0.52, 0.78, 0.98,
         1.00, 0.98, 0.75, 0.55, 0.50, 0.60, 0.82, 0.98, 1.00, 0.92, 0.66, 0.36),
        sunday_factor=0.95, ac_share=0.3, hours='almoço e jantar'),
    'shopping': Profile(
        'Shopping', Decimal(750),
        (0.22, 0.21, 0.21, 0.21, 0.21, 0.22, 0.26, 0.36, 0.55, 0.78, 0.90, 0.94,
         0.96, 0.98, 1.00, 1.00, 0.99, 0.97, 0.95, 0.93, 0.88, 0.75, 0.45, 0.28),
        (0.24, 0.22, 0.21, 0.21, 0.21, 0.22, 0.25, 0.33, 0.52, 0.78, 0.92, 0.97,
         1.00, 1.00, 1.00, 1.00, 0.99, 0.98, 0.96, 0.94, 0.88, 0.75, 0.45, 0.28),
        sunday=(0.22, 0.21, 0.21, 0.21, 0.21, 0.21, 0.23, 0.26, 0.32, 0.40, 0.52, 0.66,
                0.80, 0.90, 0.96, 0.97, 0.96, 0.94, 0.90, 0.84, 0.66, 0.42, 0.30, 0.24),
        ac_share=0.45, hours='10–22 h (domingo 14–20 h)'),
}
SIZES = {'pequeno': ('Pequeno', Decimal('0.6')), 'medio': ('Médio', Decimal(1)), 'grande': ('Grande', Decimal('1.6'))}
DEFAULT_PROFILE = 'conveniencia'
DEFAULT_SIZE = 'medio'


def profile_key(value) -> str:
    return value if value in PROFILES else DEFAULT_PROFILE


def size_key(value) -> str:
    return value if value in SIZES else DEFAULT_SIZE


def profile_label(profile=None, size=None) -> str:
    """``Loja de conveniência · porte médio``."""
    return f"{PROFILES[profile_key(profile)].label} · porte {SIZES[size_key(size)][0].lower()}"


def peak_kw(profile=None, size=None) -> Decimal:
    """Pico típico do estabelecimento (verão, dia útil), em kW."""
    return (PROFILES[profile_key(profile)].peak_kw * SIZES[size_key(size)][1]).quantize(STEP, rounding=ROUND_HALF_UP)


def default_site_limit_kw(profile=None, size=None) -> Decimal:
    """Limite contratado padrão: ``max(75 kW do Grupo B, pico × 1,3)`` em passos de 10 kW."""
    sized = peak_kw(profile, size) * LIMIT_MARGIN
    rounded = (sized / LIMIT_STEP_KW).to_integral_value(rounding=ROUND_CEILING) * LIMIT_STEP_KW
    return max(GROUP_B_LIMIT_KW, rounded).quantize(STEP)


def effective_site_limit(configured, profile=None, size=None) -> tuple[Decimal, bool]:
    """``(limite em kW, é o padrão?)``: o informado pelo dono ou o padrão do tipo/porte."""
    if configured is not None:
        return Decimal(str(configured)), False
    return default_site_limit_kw(profile, size), True


def local(moment: datetime) -> datetime:
    """Hora local de Brasília; ``datetime`` sem fuso é tratado como UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LOCAL_TZ)


def window_start(moment: datetime) -> datetime:
    """Início da janela de 5 min que contém ``moment`` (em UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = math.floor(moment.timestamp() / WINDOW_SECONDS) * WINDOW_SECONDS
    return datetime.fromtimestamp(stamp, tz=timezone.utc)


def _day_curve(profile: Profile, day: date) -> tuple:
    weekday = day.weekday()
    if weekday < 5:
        return profile.weekday
    if weekday == 5:
        return profile.saturday
    if profile.sunday is not None:
        return profile.sunday
    return tuple(value * profile.sunday_factor for value in profile.saturday)


def _hour_value(profile: Profile, moment: datetime) -> float:
    return _day_curve(profile, moment.date())[moment.hour]


def curve_fraction(profile, moment: datetime) -> float:
    """Fração do pico pela curva (sem estação, dia nem ruído), interpolada entre as horas locais."""
    item = PROFILES[profile_key(profile)]
    at = local(moment)
    start = at.replace(minute=0, second=0, microsecond=0)
    weight = (at - start).total_seconds() / 3600
    return (_hour_value(item, start) * (1 - weight)
            + _hour_value(item, start + timedelta(hours=1)) * weight)


def season_factor(profile, moment: datetime) -> float:
    """1 no auge do verão (início de fevereiro); no inverno cai ``ac_share × 35 %``."""
    item = PROFILES[profile_key(profile)]
    day = local(moment).timetuple().tm_yday
    summer = (1 + math.cos(2 * math.pi * (day - 35) / 365.25)) / 2
    return 1 - item.ac_share * SEASON_DEPTH * (1 - summer)


def _unit(key: str) -> float:
    """Número reproduzível em [−1, 1] (SHA-256; o ``hash`` do Python muda a cada processo)."""
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], 'big') / float(1 << 63) - 1.0


def _smooth(seed: str, seconds: float, period: int) -> float:
    index = math.floor(seconds / period)
    fraction = (seconds - index * period) / period
    left, right = _unit(f'{seed}:{period}:{index}'), _unit(f'{seed}:{period}:{index + 1}')
    weight = (1 - math.cos(math.pi * fraction)) / 2
    return left + (right - left) * weight


def variation(seed, moment: datetime) -> float:
    """Fator de variação (dia × ruído suave) reproduzível por posto e janela; ~0,88 a 1,12."""
    start = window_start(moment)
    seconds = start.timestamp()
    noise = sum(amplitude * _smooth(str(seed), seconds, period) for period, amplitude in NOISE)
    # Dia mais quente ou mais frio: nós à meia-noite local, interpolados (sem salto na virada do dia).
    day = DAY_SWING * _smooth(f'{seed}:day', seconds + local(start).utcoffset().total_seconds(), 86400)
    return (1 + day) * (1 + noise)


def ceiling_kw(site_limit_kw) -> Decimal | None:
    """Maior consumo simulado aceito com este limite (85 %), ou ``None`` sem limite."""
    if site_limit_kw is None:
        return None
    return (Decimal(str(site_limit_kw)) * MAX_LOAD_SHARE).quantize(STEP, rounding=ROUND_DOWN)


def simulate(seed, moment: datetime, profile=None, size=None, site_limit_kw=None) -> Decimal:
    """Consumo SIMULADO da loja (kW, passos de 0,1) no posto ``seed`` na janela de ``moment``.

    Determinístico: mesmo posto, tipo, porte, limite e janela de 5 min → mesmo valor.
    Nunca negativo e nunca acima de 85 % do limite contratado (quando informado)."""
    start = window_start(moment)
    value = (float(peak_kw(profile, size)) * curve_fraction(profile, start) * season_factor(profile, start)
             * variation(seed, start))
    result = Decimal(str(max(0.0, value))).quantize(STEP, rounding=ROUND_HALF_UP)
    top = ceiling_kw(site_limit_kw)
    return min(result, top) if top is not None else result
