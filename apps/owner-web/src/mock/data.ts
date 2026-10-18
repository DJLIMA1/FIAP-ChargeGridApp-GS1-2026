/**
 * DEV-ONLY: dados fictícios no formato da API ChargeGrid. Os totais de 7 dias
 * reproduzem a referência visual (receita R$ 8.420, 2.184 kWh, 184 recargas,
 * ticket R$ 45,76). Nunca é incluído no build de produção.
 */
import type { AlertItem, Coupon, Heatmap, LiveItem, Overview, SessionItem, Station, Timeseries } from '../api/types'
import { localDate, localMidnight } from '../lib/period'

const DAY = 86_400_000
const HOUR = 3_600_000
export const DAILY_REVENUE = 8420 / 7
const KWH_PER_REAL = 2184 / 8420
const TICKET = 8420 / 184

function rng(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const id = (prefix: string, n: number) => `${prefix}${n.toString(16).padStart(4, '0')}-6b1e-4c7a-9d2f-${(n * 7919).toString(16).padStart(12, '0')}`

export const STATIONS: Station[] = [
  {
    id: id('a1', 1), owner_id: id('f0', 1), name: 'Villa Lobos', address: 'Av. Prof. Fonseca Rodrigues, 2001 · Alto de Pinheiros, São Paulo',
    latitude: -23.5466, longitude: -46.7222, active: true,
    amenities: [{ kind: 'cafe', name: 'Café do Parque', distance_m: 120 }, { kind: 'banheiro', name: '', distance_m: 40 }],
    connectors: [],
  },
  {
    id: id('a1', 2), owner_id: id('f0', 1), name: 'Marginal Pinheiros', address: 'Av. das Nações Unidas, 4777 · Pinheiros, São Paulo',
    latitude: -23.5689, longitude: -46.6981, active: true,
    amenities: [{ kind: 'shopping', name: 'Shopping Eldorado', distance_m: 350 }, { kind: 'restaurante', name: 'Praça de alimentação', distance_m: 380 }],
    connectors: [],
  },
  {
    id: id('a1', 3), owner_id: id('f0', 1), name: 'Villa Olímpia', address: 'R. Funchal, 418 · Vila Olímpia, São Paulo',
    latitude: -23.5952, longitude: -46.6862, active: true,
    amenities: [{ kind: 'conveniencia', name: 'Conveniência 24h', distance_m: 60 }],
    connectors: [],
  },
]

const POINTS: { station: number; code: string; type: string; kw: string; price: string; share: number; status: string; online: boolean; active?: boolean }[] = [
  { station: 0, code: 'CG-001', type: 'CCS2', kw: '60.000', price: '1.8900', share: 0.16, status: 'charging', online: true },
  { station: 0, code: 'CG-002', type: 'Tipo 2', kw: '22.000', price: '1.6900', share: 0.12, status: 'available', online: true },
  { station: 0, code: 'CG-003', type: 'Tipo 2', kw: '22.000', price: '1.6900', share: 0.07, status: 'available', online: true },
  { station: 1, code: 'CG-004', type: 'CCS2', kw: '120.000', price: '2.1900', share: 0.18, status: 'charging', online: true },
  { station: 1, code: 'CG-005', type: 'CCS2', kw: '60.000', price: '1.8900', share: 0.13, status: 'reserved', online: true },
  { station: 1, code: 'CG-006', type: 'Tipo 2', kw: '22.000', price: '1.6900', share: 0.08, status: 'available', online: true },
  { station: 1, code: 'CG-007', type: 'Tipo 2', kw: '7.400', price: '1.4900', share: 0.04, status: 'offline', online: false },
  { station: 2, code: 'CG-008', type: 'CCS2', kw: '60.000', price: '1.9900', share: 0.14, status: 'charging', online: true },
  { station: 2, code: 'CG-009', type: 'Tipo 2', kw: '22.000', price: '1.7900', share: 0.08, status: 'fault', online: true },
  { station: 2, code: 'CG-010', type: 'Tipo 2', kw: '22.000', price: '1.7900', share: 0, status: 'disabled', online: false, active: false },
]

POINTS.forEach((p, index) => {
  STATIONS[p.station].connectors.push({
    id: id('c0', index + 1), station_id: STATIONS[p.station].id, public_code: p.code, connector_type: p.type,
    power_kw: p.kw, price_per_kwh: p.price, max_duration_minutes: p.kw.startsWith('120') ? 45 : 60, active: p.active ?? true,
    control_version: 3, available: p.status === 'available', availability_status: p.status, reserved_until: null,
    online: p.online, physical_state: p.status === 'fault' ? 'fault' : p.status === 'charging' ? 'charging' : 'idle', retired: false,
  })
})

export const stationShare = (stationId?: string | null) => {
  if (!stationId) return 1
  const index = STATIONS.findIndex((s) => s.id === stationId)
  return POINTS.filter((p) => p.station === index).reduce((sum, p) => sum + p.share, 0)
}
const pointsFor = (stationId?: string | null) =>
  POINTS.map((p, index) => ({ ...p, index, connector: STATIONS[p.station].connectors.find((c) => c.public_code === p.code)! })).filter(
    (p) => !stationId || STATIONS[p.station].id === stationId,
  )

// Perfil por dia da semana (Seg..Dom) e por hora — sobe ao longo da semana, como na referência.
const WEEK = [0.8, 0.95, 0.91, 1.09, 1.02, 1.2, 1.31]
const HOURS = [0.2, 0.1, 0.08, 0.06, 0.08, 0.2, 0.55, 1.3, 1.6, 1.1, 0.9, 1.0, 1.25, 1.2, 0.95, 0.9, 1.05, 1.6, 1.9, 1.7, 1.25, 0.9, 0.6, 0.35]
const HOURS_SUM = HOURS.reduce((a, b) => a + b, 0)

function weekdayIndex(instant: number) {
  const name = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Sao_Paulo', weekday: 'short' }).format(new Date(instant))
  return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(name)
}
function localHour(instant: number) {
  return Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/Sao_Paulo', hour: '2-digit', hourCycle: 'h23' }).format(new Date(instant)))
}
const iso = (instant: number) => new Date(instant).toISOString()
const localIso = (instant: number) => {
  const day = localDate(instant)
  const hour = String(localHour(instant)).padStart(2, '0')
  return `${day}T${hour}:00:00-03:00`
}

export function buckets(from: number, to: number, granularity: 'hour' | 'day'): number[] {
  const list: number[] = []
  let current = granularity === 'day' ? localMidnight(localDate(from)).getTime() : Math.floor(from / HOUR) * HOUR
  while (current < to) {
    list.push(current)
    current = granularity === 'day' ? localMidnight(localDate(current), 1).getTime() : current + HOUR
  }
  return list
}

function weightFor(instant: number, granularity: 'hour' | 'day') {
  const day = WEEK[weekdayIndex(instant)] ?? 1
  return granularity === 'day' ? day : (day * HOURS[localHour(instant)]) / (HOURS_SUM / 24)
}

/** Distribui um total pelos baldes com pesos (maiores restos), fechando a soma exata. */
function distribute(total: number, weights: number[], digits: number): number[] {
  const sum = weights.reduce((a, b) => a + b, 0) || 1
  const factor = 10 ** digits
  const units = Math.round(total * factor)
  const raw = weights.map((w) => (units * w) / sum)
  const values = raw.map(Math.floor)
  let left = units - values.reduce((a, b) => a + b, 0)
  const order = raw.map((v, i) => [v - Math.floor(v), i] as const).sort((x, y) => y[0] - x[0])
  for (let k = 0; left > 0 && order.length; k = (k + 1) % order.length, left--) values[order[k][1]] += 1
  return values.map((v) => v / factor)
}

function totals(from: number, to: number, stationId?: string | null) {
  // 7 dias de calendário = exatamente os totais da referência; "hoje" usa a fração do dia já decorrida.
  const days = buckets(from, to, 'day').length
  const effective = days === 1 ? Math.max(1 / 24, (to - from) / DAY) : days
  const revenue = Math.round(DAILY_REVENUE * effective * stationShare(stationId) * 100) / 100
  return { revenue, energy: Math.round(revenue * KWH_PER_REAL * 1000) / 1000, sessions: Math.round(revenue / TICKET) }
}

export function timeseries(from: number, to: number, granularity: 'hour' | 'day', stationId?: string | null): Timeseries {
  const keys = buckets(from, to, granularity)
  const weights = keys.map((k) => weightFor(k, granularity))
  const t = totals(from, to, stationId)
  const revenue = distribute(t.revenue, weights, 2)
  const energy = distribute(t.energy, weights, 3)
  const sessions = distribute(t.sessions, weights, 0)
  return {
    granularity, timezone: 'America/Sao_Paulo', basis: 'ended_at',
    buckets: keys.map((k) => (granularity === 'day' ? `${localDate(k)}T00:00:00-03:00` : localIso(k))),
    series: { revenue: revenue.map((v) => v.toFixed(2)), energy_kwh: energy.map((v) => v.toFixed(3)), sessions },
  }
}

export function overview(from: number, to: number, stationId?: string | null): Overview {
  const t = totals(from, to, stationId)
  const pts = pointsFor(stationId)
  const published = pts.filter((p) => p.active !== false)
  const online = published.filter((p) => p.online)
  const reservations = Math.round(t.sessions * 0.22)
  const noShows = Math.round(reservations * 0.12)
  const shares = published.reduce((sum, p) => sum + p.share, 0) || 1
  const ranking = pts
    .map((p) => {
      const share = p.share / shares
      return {
        connector_id: p.connector.id, station_id: STATIONS[p.station].id, station_name: STATIONS[p.station].name, public_code: p.code,
        revenue: (t.revenue * share).toFixed(2), energy_kwh: (t.energy * share).toFixed(3), sessions: Math.round(t.sessions * share),
        occupancy_percent: (p.share * 160).toFixed(1),
      }
    })
    .sort((a, b) => Number(b.revenue) - Number(a.revenue))
  return {
    period: { from: iso(from), to: iso(to), timezone: 'America/Sao_Paulo' },
    station_id: stationId ?? null,
    kpis: {
      revenue: t.revenue.toFixed(2), energy_wh: (t.energy * 1000).toFixed(3), energy_kwh: t.energy.toFixed(3), sessions: t.sessions,
      average_ticket: t.sessions ? (t.revenue / t.sessions).toFixed(2) : null, occupancy_percent: published.length ? '23.4' : null,
      uptime_percent: published.length ? ((online.length * 100) / published.length).toFixed(1) : null, reservations, no_shows: noShows,
      no_show_percent: reservations ? ((noShows * 100) / reservations).toFixed(1) : null, interrupted_sessions: Math.round(t.sessions * 0.02),
      failed_sessions: Math.round(t.sessions * 0.006), active_sessions: pts.filter((p) => p.status === 'charging').length,
      points: published.length, points_online: online.length,
    },
    stations: {
      total: stationId ? 1 : STATIONS.length, active: stationId ? 1 : STATIONS.filter((s) => s.active).length,
      points: pts.length, points_published: published.length, points_online: online.length,
    },
    ranking,
    generated_at: new Date().toISOString(),
  }
}

export function heatmap(from: number, to: number, stationId?: string | null): Heatmap {
  const t = totals(from, to, stationId)
  const random = rng(42)
  const weights: number[][] = WEEK.map((day) => HOURS.map((hour) => day * hour * (0.75 + random() * 0.5)))
  const flat = distribute(t.sessions, weights.flat(), 0)
  const cells = WEEK.map((_, d) => flat.slice(d * 24, d * 24 + 24).map((v) => Math.max(0, v)))
  const max = Math.max(0, ...cells.flat())
  const hourly = HOURS.map((_, h) => cells.reduce((sum, row) => sum + row[h], 0))
  const peak_hours = hourly
    .map((sessions, hour) => ({ hour, sessions }))
    .filter((p) => p.sessions)
    .sort((a, b) => b.sessions - a.sessions || a.hour - b.hour)
    .slice(0, 3)
  return { timezone: 'America/Sao_Paulo', basis: 'started_at', days: ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'], hours: [...Array(24).keys()], cells, max, peak_hours }
}

let liveTick = 0
export function live(stationId?: string | null): { items: LiveItem[]; generated_at: string } {
  liveTick += 1
  const now = Date.now()
  const items = pointsFor(stationId).map((p, index): LiveItem => {
    const station = STATIONS[p.station]
    const c = p.connector
    const charging = p.status === 'charging'
    const minutes = 18 + index * 7 + liveTick * 0.5
    const powerW = Number(c.power_kw) * 1000 * (0.82 + ((index * 13) % 10) / 100)
    return {
      connector_id: c.id, station_id: station.id, station_name: station.name, station_active: station.active, public_code: c.public_code,
      connector_type: c.connector_type, power_kw: c.power_kw, price_per_kwh: c.price_per_kwh, max_duration_minutes: c.max_duration_minutes,
      active: c.active, retired: false, has_device: p.code !== 'CG-010', device_id: p.code !== 'CG-010' ? id('d0', index + 1) : null,
      online: p.online, last_seen: p.online ? iso(now - 8000) : p.code === 'CG-010' ? null : iso(now - 3 * HOUR - 12 * 60000),
      firmware_version: '0.5.1', physical_state: c.physical_state ?? 'idle', available: p.status === 'available',
      availability_status: c.active ? p.status : 'disabled', reserved_until: p.status === 'reserved' ? iso(now + 11 * 60000) : null,
      session: charging
        ? {
            id: id('e0', index + 1), status: 'charging', started_at: iso(now - minutes * 60000),
            energy_wh: ((powerW * minutes) / 60).toFixed(3), cost_estimate: (((powerW * minutes) / 60000) * Number(c.price_per_kwh)).toFixed(4),
            soc_percent: String(Math.min(96, 34 + index * 6 + liveTick)), power_w: powerW.toFixed(0), source: 'measured', last_measurement_at: iso(now - 5000),
          }
        : null,
    }
  })
  return { items, generated_at: iso(now) }
}

export function alerts(stationId?: string | null): { items: AlertItem[]; generated_at: string } {
  const now = Date.now()
  const pts = pointsFor(stationId)
  const base = (code: string) => {
    const p = pts.find((x) => x.code === code)
    return p ? { connector_id: p.connector.id, station_id: STATIONS[p.station].id, station_name: STATIONS[p.station].name, public_code: code } : null
  }
  const list: (AlertItem | null)[] = [
    base('CG-007') && { ...base('CG-007')!, kind: 'device_offline', severity: 'critical', title: 'Dispositivo offline', detail: 'CG-007 · Marginal Pinheiros: sem comunicação. Último contato: há 3 h.', at: iso(now - 3 * HOUR) },
    base('CG-009') && { ...base('CG-009')!, kind: 'device_fault', severity: 'critical', title: 'Falha no equipamento', detail: 'CG-009 · Villa Olímpia: o painel informou falha.', at: null },
    base('CG-004') && { ...base('CG-004')!, kind: 'command_failed', severity: 'warning', title: 'Falhas de comando', detail: 'CG-004 · Marginal Pinheiros: 2 comando(s) sem confirmação nas últimas 24 h.', at: null },
    base('CG-003') && { ...base('CG-003')!, kind: 'point_idle', severity: 'info', title: 'Ponto parado', detail: 'CG-003 · Villa Lobos: nenhuma recarga desde 14/10.', at: iso(now - 4 * DAY) },
  ]
  return { items: list.filter((a): a is AlertItem => Boolean(a)), generated_at: iso(now) }
}

/** Histórico fixo de sessões dos últimos 45 dias. */
const SESSION_POOL: SessionItem[] = (() => {
  const random = rng(7)
  const now = Date.now()
  const pool: SessionItem[] = []
  const eligible = POINTS.filter((p) => p.share > 0)
  const shareSum = eligible.reduce((s, p) => s + p.share, 0)
  for (let day = 0; day < 45; day++) {
    const dayStart = localMidnight(localDate(now), -day).getTime()
    const count = Math.round((184 / 7) * WEEK[weekdayIndex(dayStart)] / 1.04 * (0.9 + random() * 0.2) * (day === 0 ? Math.min(1, (now - dayStart) / DAY) : 1))
    for (let i = 0; i < count; i++) {
      let pick = random() * shareSum
      const point = eligible.find((p) => (pick -= p.share) <= 0) ?? eligible[0]
      const station = STATIONS[point.station]
      const connector = station.connectors.find((c) => c.public_code === point.code)!
      let hourPick = random() * HOURS_SUM
      const hour = HOURS.findIndex((h) => (hourPick -= h) <= 0)
      const created = dayStart + Math.max(0, hour) * HOUR + Math.floor(random() * 55) * 60000
      if (created > now - 5 * 60000) continue
      const roll = random()
      const status = day === 0 && created > now - 40 * 60000 ? 'charging' : roll < 0.02 ? 'failed' : roll < 0.05 ? 'interrupted' : 'completed'
      const started = status === 'failed' ? null : created + 40000
      const duration = 18 + Math.floor(random() * 50)
      const ended = status === 'charging' ? null : status === 'failed' ? created + 90000 : (started ?? created) + duration * 60000
      const kwh = status === 'failed' ? 0 : Math.round((TICKET / Number(connector.price_per_kwh)) * (0.55 + random() * 0.9) * 1000) / 1000
      const discount = random() < 0.12 ? 10 : 0
      const cost = kwh * Number(connector.price_per_kwh) * (1 - discount / 100)
      pool.push({
        id: `${(created / 1000).toString(16)}-${pool.length.toString(16).padStart(4, '0')}-4e2a-9c3d-${(pool.length * 104729).toString(16).padStart(12, '0')}`,
        station_id: station.id, station_name: station.name, connector_id: connector.id, public_code: connector.public_code, status,
        created_at: iso(created), started_at: started ? iso(started) : null, ended_at: ended ? iso(ended) : null,
        duration_minutes: started ? (((ended ?? now) - started) / 60000).toFixed(1) : null, energy_kwh: kwh.toFixed(3),
        price_per_kwh: connector.price_per_kwh, discount_percent: discount, cost_estimate: cost.toFixed(4),
        source: random() < 0.85 ? 'measured' : 'estimated',
        end_reason: status === 'completed' ? (random() < 0.7 ? 'requested' : 'duration_limit') : status === 'interrupted' ? 'communication_lost' : status === 'failed' ? 'start_timeout' : '',
      })
    }
  }
  return pool.sort((a, b) => (a.created_at! < b.created_at! ? 1 : -1))
})()

export function sessions(params: URLSearchParams) {
  const from = Date.parse(params.get('from') ?? '') || Date.now() - 7 * DAY
  const to = Date.parse(params.get('to') ?? '') || Date.now()
  const station = params.get('station_id')
  const status = (params.get('status') ?? '').split(',').filter(Boolean)
  const q = (params.get('q') ?? '').trim().toLowerCase()
  const limit = Math.min(100, Number(params.get('limit') ?? 25))
  const offset = Number(params.get('offset') ?? 0)
  const items = SESSION_POOL.filter((s) => {
    const created = Date.parse(s.created_at!)
    if (created < from || created >= to) return false
    if (station && s.station_id !== station) return false
    if (status.length && !status.includes(s.status)) return false
    if (q && !(s.station_name.toLowerCase().includes(q) || s.public_code.toLowerCase().includes(q) || s.id.startsWith(q))) return false
    return true
  })
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
}

export const COUPONS: Coupon[] = [
  { id: id('b0', 1), operator_id: id('f0', 1), station_id: null, code: 'VERAO10', description: '10% de desconto em qualquer estação durante o verão', discount_percent: 10, valid_until: iso(Date.now() + 60 * DAY), active: true },
  { id: id('b0', 2), operator_id: id('f0', 1), station_id: STATIONS[2].id, code: 'MADRUGADA15', description: 'Recargas entre 22h e 6h na Villa Olímpia', discount_percent: 15, valid_until: iso(Date.now() + 20 * DAY), active: true },
  { id: id('b0', 3), operator_id: id('f0', 1), station_id: STATIONS[1].id, code: 'INAUGURA20', description: 'Inauguração da Marginal Pinheiros', discount_percent: 20, valid_until: iso(Date.now() - 12 * DAY), active: false },
]
