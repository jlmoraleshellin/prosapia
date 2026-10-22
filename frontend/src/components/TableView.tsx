import type { ColumnMeta, Frame } from '../api'
import { basename, col, fmt } from '../frame'
import type { Sort } from '../store'

const LIMIT = 300

export default function TableView({
  frame,
  columns,
  rows,
  sort,
  onSort,
  current,
  selected,
  onToggleSelect,
  onPick,
}: {
  frame: Frame
  columns: ColumnMeta[]
  rows: number[]
  sort: Sort
  onSort: (s: Sort) => void
  current?: string
  selected: Set<string>
  onToggleSelect: (name: string) => void
  onPick: (name: string) => void
}) {
  const cols = columns.map((c) => ({ meta: c, values: col(frame, c.name) ?? [] }))
  const nameCol = col(frame, 'name') ?? []
  const shown = rows.slice(0, LIMIT)
  const click = (name: string) =>
    onSort(sort.col === name ? { col: name, dir: sort.dir === 1 ? -1 : 1 } : { col: name, dir: 1 })
  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            <th className="sticky top-0 z-10 w-8 border-b border-zinc-200 bg-white/95 pl-3 backdrop-blur" />
            {cols.map(({ meta }) => (
              <th
                key={meta.name}
                onClick={() => click(meta.name)}
                className={`sticky top-0 z-10 cursor-pointer select-none whitespace-nowrap border-b border-zinc-200 bg-white/95 px-3 py-2 text-left text-[11px] font-semibold tracking-wide backdrop-blur-sm hover:text-indigo-600 ${sort.col === meta.name ? 'text-indigo-600' : 'text-zinc-500'}`}
              >
                {meta.name}
                {sort.col === meta.name ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
                {meta.source !== 'own' && <span className="ml-1 rounded bg-zinc-100 px-1 font-normal text-[10px] text-zinc-500">{meta.source}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((i) => {
            const name = String(nameCol[i])
            const isCurrent = name === current
            return (
              <tr key={i} onClick={() => onPick(name)} className={`cursor-pointer ${isCurrent ? 'bg-indigo-50/70' : 'hover:bg-zinc-50'}`}>
                <td className={`w-8 border-b border-zinc-100 pl-3 ${isCurrent ? 'shadow-[inset_3px_0_0_theme(colors.indigo.500)]' : ''}`} onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="accent-pink-600" checked={selected.has(name)} onChange={() => onToggleSelect(name)} />
                </td>
                {cols.map(({ meta, values }) => {
                  const v = values[i]
                  const text = meta.is_path && typeof v === 'string' ? basename(v) : fmt(v)
                  return (
                    <td
                      key={meta.name}
                      title={v == null ? '' : String(v)}
                      className={`h-8 max-w-[280px] truncate border-b border-zinc-100 px-3 ${meta.is_numeric ? 'text-right tabular-nums' : ''} ${meta.name === 'name' ? 'font-medium text-zinc-900' : ''}`}
                    >
                      {text}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      {rows.length > LIMIT && (
        <div className="p-3 text-xs text-zinc-500">Showing {LIMIT} of {rows.length} rows; sort or filter to see others. Plots and export use all of them.</div>
      )}
    </div>
  )
}
