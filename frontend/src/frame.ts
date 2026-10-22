import type { Cell, Frame } from './api'
import type { Filter, Sort } from './store'

export function col(frame: Frame, name: string | undefined): Cell[] | undefined {
  if (!name) return undefined
  const i = frame.names.indexOf(name)
  return i < 0 ? undefined : frame.cols[i]
}

export function names(frame: Frame): string[] {
  return (col(frame, 'name') ?? []).map(String)
}

function passes(frame: Frame, f: Filter, i: number): boolean {
  const v = col(frame, f.col)?.[i]
  if (v == null) return false
  if (f.values?.length) return f.values.includes(String(v))
  if (f.text) return String(v).toLowerCase().includes(f.text.toLowerCase())
  if (typeof v === 'number') {
    if (f.min != null && v < f.min) return false
    if (f.max != null && v > f.max) return false
  }
  return true
}

export function filterRows(frame: Frame, filters: Filter[], mode: 'any' | 'all', search: string): number[] {
  const n = frame.cols[0]?.length ?? 0
  const nm = col(frame, 'name')
  const q = search.trim().toLowerCase()
  const active = filters.filter((f) => f.col && (f.min != null || f.max != null || f.values?.length || f.text))
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    if (q && !String(nm?.[i] ?? '').toLowerCase().includes(q)) continue
    if (active.length) {
      const hits = active.map((f) => passes(frame, f, i))
      if (mode === 'all' ? !hits.every(Boolean) : !hits.some(Boolean)) continue
    }
    out.push(i)
  }
  return out
}

export function sortRows(frame: Frame, rows: number[], sort: Sort): number[] {
  const c = col(frame, sort.col ?? undefined)
  if (!c) return rows
  const key = (v: Cell) => (v == null ? null : typeof v === 'number' ? v : String(v))
  return [...rows].sort((a, b) => {
    const x = key(c[a])
    const y = key(c[b])
    if (x === null) return 1
    if (y === null) return -1
    return (x < y ? -1 : x > y ? 1 : 0) * sort.dir
  })
}

export function fmt(v: Cell): string {
  if (v == null) return ''
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toPrecision(4)
  return String(v)
}

export function basename(p: string): string {
  return p.split('/').pop() ?? p
}

export function toTSV(frame: Frame, rows: number[], columns: string[]): string {
  const cols = columns.map((n) => col(frame, n) ?? [])
  const lines = [columns.join('\t')]
  for (const i of rows) lines.push(cols.map((c) => (c[i] == null ? '' : String(c[i]))).join('\t'))
  return lines.join('\n') + '\n'
}

export function download(text: string, filename: string, type = 'text/plain') {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type }))
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
