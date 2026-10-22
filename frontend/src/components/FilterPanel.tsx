import type { ColumnMeta, Frame } from '../api'
import { col } from '../frame'
import { withData } from '../heuristics'
import type { Filter, View } from '../store'
import { btn, btnGhost, input, select } from '../ui'

export default function FilterPanel({
  frame,
  columns,
  view,
  onView,
}: {
  frame: Frame
  columns: ColumnMeta[]
  view: View
  onView: (patch: Partial<View>) => void
}) {
  const cols = withData(columns).filter((c) => c.name !== 'name')
  const update = (id: number, patch: Partial<Filter>) =>
    onView({ filters: view.filters.map((f) => (f.id === id ? { ...f, ...patch } : f)) })
  const remove = (id: number) => onView({ filters: view.filters.filter((f) => f.id !== id) })
  const add = () => onView({ filters: [...view.filters, { id: Date.now(), col: cols[0]?.name ?? '' }] })
  const full = select + ' w-full max-w-none'

  return (
    <aside className="flex w-60 flex-none flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="flex flex-none items-center gap-2 border-b border-zinc-200 px-3 py-2">
        <span className="text-xs font-semibold">Filters</span>
        <select className={select + ' h-6 text-[11px]'} value={view.filterMode} onChange={(e) => onView({ filterMode: e.target.value as View['filterMode'] })} title="How filters combine">
          <option value="all">match all</option>
          <option value="any">match any</option>
        </select>
        <span className="flex-1" />
        <button className={btn + ' h-6'} onClick={add}>+ Add</button>
        <button className={btnGhost + ' h-6 w-6'} onClick={() => onView({ showFilters: false })}>×</button>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-auto p-2">
        {view.filters.map((f) => {
          const meta = columns.find((c) => c.name === f.col)
          const values = meta && !meta.is_numeric && (meta.n_unique ?? 0) <= 50
            ? [...new Set((col(frame, f.col) ?? []).filter((v) => v != null).map(String))].sort()
            : null
          return (
            <div className="space-y-1.5 rounded-lg border border-zinc-200 bg-white p-2 shadow-sm" key={f.id}>
              <div className="flex items-center gap-1">
                <select className={full} value={f.col} onChange={(e) => update(f.id, { col: e.target.value, min: null, max: null, values: undefined, text: '' })}>
                  {cols.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                      {c.is_numeric ? '' : ' (cat)'}
                    </option>
                  ))}
                </select>
                <button className={btnGhost + ' h-6 w-6 flex-none'} onClick={() => remove(f.id)} title="Remove">×</button>
              </div>
              {meta?.is_numeric ? (
                <div className="flex items-center gap-1">
                  <input className={input + ' w-full min-w-0'} type="number" step="any" placeholder={`min ${meta.min?.toPrecision(3) ?? ''}`} value={f.min ?? ''}
                    onChange={(e) => update(f.id, { min: e.target.value === '' ? null : Number(e.target.value) })} />
                  <span className="text-zinc-400">–</span>
                  <input className={input + ' w-full min-w-0'} type="number" step="any" placeholder={`max ${meta.max?.toPrecision(3) ?? ''}`} value={f.max ?? ''}
                    onChange={(e) => update(f.id, { max: e.target.value === '' ? null : Number(e.target.value) })} />
                </div>
              ) : values ? (
                <select multiple className={full + ' h-28'} value={f.values ?? []} onChange={(e) => update(f.id, { values: [...e.target.selectedOptions].map((o) => o.value) })}>
                  {values.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              ) : (
                <input className={input + ' w-full'} type="text" placeholder="contains…" value={f.text ?? ''} onChange={(e) => update(f.id, { text: e.target.value })} />
              )}
              {meta?.is_numeric && <div className="text-[10.5px] text-zinc-400">rows with no value are dropped once a bound is set</div>}
            </div>
          )
        })}
        {!view.filters.length && <div className="p-1 text-xs text-zinc-500">No filters. Add one to narrow the rows plotted and listed.</div>}
      </div>
    </aside>
  )
}
