import type { Heatmap as HeatmapData } from '../api/types'
import { formatNumber } from '../lib/format'

const LEVELS = [0.14, 0.32, 0.52, 0.74, 1]

function heatColor(count: number, max: number): string {
  if (!count || !max) return '#242424'
  const level = LEVELS[Math.min(LEVELS.length - 1, Math.floor((count / max) * LEVELS.length - 1e-9))]
  return `rgba(61, 190, 122, ${level})`
}

export function HeatmapGrid({ data }: { data: HeatmapData }) {
  return (
    <div>
      <div className="heatmap" role="table" aria-label="Sessões por dia da semana e hora (início da recarga, horário de São Paulo)">
        <span />
        {data.hours.map((hour) => (
          <span key={hour} className="hour" aria-hidden>
            {hour}
          </span>
        ))}
        {data.days.map((day, row) => (
          <div key={day} role="row" style={{ display: 'contents' }}>
            <span className="day" role="rowheader">
              {day}
            </span>
            {data.cells[row].map((count, hour) => (
              <span
                key={hour}
                role="cell"
                className="cell"
                style={{ background: heatColor(count, data.max) }}
                title={`${day} ${String(hour).padStart(2, '0')}h: ${formatNumber(count)} ${count === 1 ? 'sessão' : 'sessões'}`}
                aria-label={`${day} ${hour}h: ${count} sessões`}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="heat-legend">
        Menos
        <span className="scale" aria-hidden>
          <i style={{ background: '#242424' }} />
          {LEVELS.map((level) => (
            <i key={level} style={{ background: `rgba(61, 190, 122, ${level})` }} />
          ))}
        </span>
        Mais
      </div>
    </div>
  )
}
