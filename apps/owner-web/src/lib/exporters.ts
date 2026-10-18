/**
 * Exportação client-side do resultado filtrado de sessões, no mesmo formato da
 * API (`/owner/export/sessions.csv|json`): CSV RFC 4180 com cabeçalho em
 * português e proteção contra injeção de fórmulas; JSON com envelope
 * `schema_version`.
 */
import type { SessionItem } from '../api/types'

export const SESSION_COLUMNS: [keyof SessionItem, string][] = [
  ['id', 'ID da sessão'],
  ['station_name', 'Posto'],
  ['public_code', 'Ponto'],
  ['status', 'Status'],
  ['created_at', 'Criada em'],
  ['started_at', 'Início'],
  ['ended_at', 'Fim'],
  ['duration_minutes', 'Duração (min)'],
  ['energy_kwh', 'Energia (kWh)'],
  ['price_per_kwh', 'Tarifa (R$/kWh)'],
  ['discount_percent', 'Desconto (%)'],
  ['cost_estimate', 'Valor estimado (R$)'],
  ['source', 'Origem da medição'],
  ['end_reason', 'Motivo de término'],
]

const FORMULA_PREFIXES = ['=', '+', '-', '@', '\t', '\r', '\n']
const NUMERIC = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/

/** Neutraliza fórmulas (CSV injection) sem alterar números legítimos. */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'sim' : 'não'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  let text = String(value)
  if (FORMULA_PREFIXES.some((prefix) => text.startsWith(prefix)) && !NUMERIC.test(text)) text = `'${text}`
  if (/[",\r\n]/.test(text)) text = `"${text.replace(/"/g, '""')}"`
  return text
}

export function toCsv<T extends object>(rows: T[], columns: [keyof T, string][]): string {
  const lines = [columns.map(([, header]) => csvCell(header)).join(',')]
  for (const row of rows) lines.push(columns.map(([key]) => csvCell(row[key])).join(','))
  return lines.join('\r\n') + '\r\n'
}

export function sessionsCsv(rows: SessionItem[]): string {
  return toCsv(rows, SESSION_COLUMNS)
}

export function sessionsJson(rows: SessionItem[], filters: Record<string, unknown>, generatedAt: Date = new Date()): string {
  const envelope = {
    schema_version: 1,
    dataset: 'sessions',
    generated_at: generatedAt.toISOString(),
    timezone: 'America/Sao_Paulo',
    currency: 'BRL',
    units: { energy: 'kWh', duration: 'min' },
    filters: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== null && value !== undefined && value !== '')),
    total: rows.length,
    notes: 'Valores estimados; energia pode ser simulada, medida ou estimada (coluna source).',
    items: rows,
  }
  return JSON.stringify(envelope, null, 2)
}

/** "chargegrid-sessoes-20261018-1405.csv" no horário de São Paulo. */
export function exportFilename(ext: 'csv' | 'json', now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `chargegrid-sessoes-${get('year')}${get('month')}${get('day')}-${get('hour')}${get('minute')}.${ext}`
}

export function downloadText(filename: string, content: string, mime: string): void {
  // BOM para o Excel reconhecer UTF-8 nos CSVs.
  const blob = new Blob([mime.startsWith('text/csv') ? '﻿' + content : content], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
