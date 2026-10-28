import { Fragment } from 'react'
import type { ColumnMeta, Frame } from '../api'
import { col } from '../frame'
import { withData } from '../heuristics'
import type { Filter, View } from '../store'
import { btn, btnGhost, input, select } from '../ui'

const PILLS = 12 // up to this many distinct values: checkboxes; up to 50: a list; beyond: free text

function distinct(frame: Frame, name: string): string[] {
  return [...new Set((col(frame, name) ?? []).filter((v) => v != null).map(String))].sort()
}

function kindOf(c: ColumnMeta, values: string[]): 'num' | 'bool' | 'text' {
  if (c.is_numeric) return 'num'
  return values.length && values.every((v) => v === 'true' || v === 'false') ? 'bool' : 'text'
}

export default function FilterPanel({ frame, columns, view, onView }: { frame: Frame; columns: ColumnMeta[]; view: View; onView: (patch: Partial<View>) => void }) {
  const cols = withData(columns).filter((c) => c.name !== 'name')
  const update = (id: number, patch: Partial<Filter>) => onView({ filters: view.filters.map((f) => (f.id === id ? { ...f, ...patch } : f)) })
  const remove = (id: number) => onView({ filters: view.filters.filter((f) => f.id !== id) })
  const add = (group: number) => onView({ filters: [...view.filters, { id: Date.now(), group, col: cols[0]?.name ?? '' }] })
  const groups = [...new Set(view.filters.map((f) => f.group ?? 0))].sort((a, b) => a - b)
  const nextGroup = (groups[groups.length - 1] ?? -1) + 1
  const full = select + ' w-full max-w-none'

  const card = (f: Filter) => {
    const meta = columns.find((c) => c.name === f.col)
    const values = meta && !meta.is_numeric && (meta.n_unique ?? 0) <= 50 ? distinct(frame, f.col) : []
    const kind = meta ? kindOf(meta, values) : 'text'
    const toggle = (v: string) => update(f.id, { values: f.values?.includes(v) ? f.values.filter((x) => x !== v) : [...(f.values ?? []), v] })
    return (
      <div className="space-y-1.5 rounded-md border border-zinc-200 bg-white p-2 shadow-sm" key={f.id}>
        <div className="flex items-center gap-1">
          <select className={full + ' min-w-0'} value={f.col} onChange={(e) => update(f.id, { col: e.target.value, min: null, max: null, values: undefined, text: '' })}>
            {cols.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} · {kindOf(c, c.is_numeric ? [] : distinct(frame, c.name))}
              </option>
            ))}
          </select>
          <button className={btn + ' h-6 flex-none px-1.5 ' + (f.not ? 'border-rose-300 bg-rose-50 text-rose-700' : '')} onClick={() => update(f.id, { not: !f.not })} title="Negate this filter">
            {f.not ? 'not' : 'is'}
          </button>
          <button className={btnGhost + ' h-6 w-6 flex-none'} onClick={() => remove(f.id)} title="Remove">×</button>
        </div>
        {kind === 'num' ? (
          <div className="flex items-center gap-1">
            <input className={input + ' w-full min-w-0'} type="number" step="any" placeholder={`min ${meta?.min?.toPrecision(3) ?? ''}`} value={f.min ?? ''}
              onChange={(e) => update(f.id, { min: e.target.value === '' ? null : Number(e.target.value) })} />
            <span className="text-zinc-400">–</span>
            <input className={input + ' w-full min-w-0'} type="number" step="any" placeholder={`max ${meta?.max?.toPrecision(3) ?? ''}`} value={f.max ?? ''}
              onChange={(e) => update(f.id, { max: e.target.value === '' ? null : Number(e.target.value) })} />
          </div>
        ) : values.length && values.length <= PILLS ? (
          <div className="flex flex-wrap gap-1">
            {values.map((v) => (
              <label key={v} className={'cursor-pointer rounded-full border px-2 py-0.5 text-[11px] ' + (f.values?.includes(v) ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-zinc-200 text-zinc-600 hover:bg-zinc-50')}>
                <input type="checkbox" className="sr-only" checked={!!f.values?.includes(v)} onChange={() => toggle(v)} />
                {v}
              </label>
            ))}
          </div>
        ) : values.length ? (
          <select multiple className={full + ' h-28'} value={f.values ?? []} onChange={(e) => update(f.id, { values: [...e.target.selectedOptions].map((o) => o.value) })}>
            {values.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input className={input + ' w-full'} type="text" placeholder="contains…" value={f.text ?? ''} onChange={(e) => update(f.id, { text: e.target.value })} />
        )}
      </div>
    )
  }

  return (
    <aside className="flex w-60 flex-none flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="flex flex-none items-center gap-2 border-b border-zinc-200 px-3 py-2">
        <span className="text-xs font-semibold">Filters</span>
        <span className="flex-1" />
        <button className={btnGhost + ' h-6 w-6'} onClick={() => onView({ showFilters: false })}>×</button>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-auto p-2">
        {groups.map((g, gi) => (
          <Fragment key={g}>
            {gi > 0 && <div className="text-center text-[11px] font-semibold uppercase tracking-wider text-zinc-400">or</div>}
            <div className="space-y-1.5 rounded-lg border border-dashed border-zinc-300 p-1.5">
              {view.filters.filter((f) => (f.group ?? 0) === g).map((f, fi) => (
                <Fragment key={f.id}>
                  {fi > 0 && <div className="pl-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">and</div>}
                  {card(f)}
                </Fragment>
              ))}
              <button className="px-1 text-[11px] font-medium text-indigo-600 hover:underline" onClick={() => add(g)}>+ and</button>
            </div>
          </Fragment>
        ))}
        <button className={btn + ' justify-center'} onClick={() => add(nextGroup)}>{groups.length ? '+ or' : '+ Add filter'}</button>
        <div className="px-1 text-[10.5px] leading-snug text-zinc-400">Filters in a box must all match; any box matching keeps the row. Empty cells never match, so “not” keeps them.</div>
      </div>
    </aside>
  )
}
