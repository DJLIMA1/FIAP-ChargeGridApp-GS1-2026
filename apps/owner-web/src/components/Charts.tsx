import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export interface Point {
  key: string
  label: string
  tooltip: string
  value: number
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: Point }[]
  format(value: number): string
  color: string
}

function ChartTooltip({ active, payload, format, color }: TooltipProps) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="t">{point.tooltip}</div>
      <div className="v">
        <span className="legend-dot" style={{ background: color }} />
        {format(point.value)}
      </div>
    </div>
  )
}

/** Linha com área (estilo das telas "Histórico" e "Consumo de energia" do app). */
export function TrendChart({ data, color, format, axisFormat, label }: { data: Point[]; color: string; format(value: number): string; axisFormat(value: number): string; label: string }) {
  const id = useId().replace(/:/g, '')
  const dense = data.length > 16
  return (
    <div className="chart-box" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 14, left: 4, bottom: 0 }}>
          <defs>
            <linearGradient id={`g-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.32} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="#2e2e2e" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#ADADAD', fontSize: 12 }}
            interval={dense ? 'preserveStartEnd' : 0}
            minTickGap={dense ? 18 : 4}
            dy={8}
          />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: '#7F7F7F', fontSize: 11 }} tickFormatter={axisFormat} width={52} allowDecimals={false} />
          <Tooltip content={<ChartTooltip format={format} color={color} />} cursor={{ stroke: '#555', strokeDasharray: '3 3' }} />
          <Area
            type="linear"
            dataKey="value"
            stroke={color}
            strokeWidth={2.5}
            fill={`url(#g-${id})`}
            dot={dense ? false : { r: 3.5, fill: '#fff', stroke: color, strokeWidth: 2 }}
            activeDot={{ r: 5, fill: '#fff', stroke: color, strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
