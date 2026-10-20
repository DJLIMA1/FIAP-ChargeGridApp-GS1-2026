import { Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ForecastPoint } from '../lib/forecast'
import { FULL_PERCENT, percent } from '../lib/forecast'
import { formatEnergy } from '../lib/format'

interface TooltipProps {
  active?: boolean
  payload?: { payload: ForecastPoint }[]
}

function ForecastTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="t">{point.tooltip}</div>
      <div className="v">
        <span className="legend-dot" style={{ background: point.full ? '#E8922B' : '#3EBF80' }} />
        Previsto: {percent(point.occupancy)}
      </div>
      <div className="v dim" style={{ fontWeight: 500 }}>
        <span className="legend-dot" style={{ background: '#6B9DFF' }} />
        Média: {percent(point.baseline)}
      </div>
      {point.band ? (
        <div className="dim" style={{ fontSize: 12 }}>
          Faixa provável: {percent(point.band[0])}–{percent(point.band[1])}
        </div>
      ) : null}
      <div className="dim" style={{ fontSize: 12 }}>Energia: {formatEnergy(point.energy.toFixed(3))}</div>
    </div>
  )
}

/** Ocupação prevista (barras), média do mesmo dia/hora (linha) e faixa p10–p90 (área). */
export function ForecastChart({ data, label }: { data: ForecastPoint[]; label: string }) {
  return (
    <div className="chart-box" role="img" aria-label={label} style={{ height: 290 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 14, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="#2e2e2e" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#ADADAD', fontSize: 11.5 }}
            interval="preserveStartEnd" minTickGap={14} dy={8} />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: '#7F7F7F', fontSize: 11 }} domain={[0, 100]}
            tickFormatter={(value: number) => `${value}%`} width={44} />
          <Tooltip content={<ForecastTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Area type="monotone" dataKey="band" stroke="none" fill="#3EBF80" fillOpacity={0.12} isAnimationActive={false} />
          <Bar dataKey="occupancy" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((point) => (
              <Cell key={point.key} fill={point.full ? '#E8922B' : '#3EBF80'} />
            ))}
          </Bar>
          <Line type="monotone" dataKey="baseline" stroke="#6B9DFF" strokeWidth={2} dot={false} strokeDasharray="4 3" isAnimationActive={false} />
          <ReferenceLine y={FULL_PERCENT} stroke="#E8922B" strokeDasharray="3 3" label={{ value: 'lotado', fill: '#E8922B', fontSize: 11, position: 'insideTopRight' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
