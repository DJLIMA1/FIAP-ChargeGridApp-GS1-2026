import type { Point } from '../components/Charts'
import type { Timeseries } from '../api/types'
import { formatDayMonth, formatTime, formatWeekday, toNumber } from './format'

export function seriesPoints(ts: Timeseries, metric: 'revenue' | 'energy_kwh' | 'sessions'): Point[] {
  const values = ts.series[metric] as (string | number)[]
  const short = ts.buckets.length <= 7
  return ts.buckets.map((bucket, index) => ({
    key: bucket,
    label: ts.granularity === 'hour' ? `${formatTime(bucket).slice(0, 2)}h` : short ? formatWeekday(bucket) : formatDayMonth(bucket),
    tooltip: ts.granularity === 'hour' ? `${formatDayMonth(bucket)} · ${formatTime(bucket)}` : `${formatWeekday(bucket)}, ${formatDayMonth(bucket)}`,
    value: toNumber(values[index]) ?? 0,
  }))
}
