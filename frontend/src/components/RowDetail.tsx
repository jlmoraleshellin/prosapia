import { Fragment, useState } from 'react'
import type { ColumnMeta, RowDetail as Detail } from '../api'
import { basename, fmt } from '../frame'
import { setRoute } from '../route'
import { chip, h4, link } from '../ui'
import FileView from './FileView'

function Fields({ row, keys }: { row: Record<string, unknown>; keys: string[] }) {
  return (
    <div className="kv">
      {keys.map((k) => (
        <Fragment key={k}>
          <span className="k">{k}</span>
          <span className={`v ${typeof row[k] === 'string' && String(row[k]).includes('/') ? 'font-mono text-[11px]' : ''}`} title={String(row[k])}>
            {fmt(row[k] as never)}
          </span>
        </Fragment>
      ))}
    </div>
  )
}

export default function RowDetail({
  detail,
  columns,
  onViewStructure,
}: {
  detail: Detail
  columns: ColumnMeta[]
  onViewStructure: (path: string, label: string) => void
}) {
  const [textPath, setTextPath] = useState<string | null>(null)
  const present = (keys: string[]) => keys.filter((k) => k !== 'name' && detail.row[k] != null && detail.row[k] !== '')
  const bySource = new Map<string, string[]>()
  for (const c of columns) {
    if (!bySource.has(c.source)) bySource.set(c.source, [])
    bySource.get(c.source)!.push(c.name)
  }
  const own = present(bySource.get('own') ?? [])
  const ancestors = [...bySource.entries()].filter(([s]) => s !== 'own')
  return (
    <div className="space-y-4 p-4">
      <div>
        <h3 className="text-base font-semibold tracking-tight text-zinc-900">{detail.name}</h3>
        <div className="font-mono text-[11px] text-zinc-500">{detail.table}</div>
      </div>
      {detail.lineage.length > 0 && (
        <div>
          <h4 className={h4}>Lineage</h4>
          <div className="flex flex-wrap items-center gap-1">
            {detail.lineage.map((a, i) => (
              <Fragment key={a.table + a.name}>
                {i > 0 && <span className="text-zinc-300">←</span>}
                <span className={chip + ' cursor-pointer hover:bg-indigo-100'} onClick={() => setRoute({ table: a.table, row: a.name })}>
                  <span className="text-indigo-400">{a.table}</span> {a.name}
                </span>
              </Fragment>
            ))}
          </div>
        </div>
      )}
      {detail.children.length > 0 && (
        <div>
          <h4 className={h4}>Children</h4>
          <div className="space-y-1">
            {detail.children.map((c) => (
              <div key={c.table} className="flex flex-wrap items-center gap-1">
                <span className="mr-1 font-mono text-[11px] text-zinc-500">{c.table}</span>
                {c.names.slice(0, 40).map((n) => (
                  <span className={chip + ' cursor-pointer hover:bg-indigo-100'} key={n} onClick={() => setRoute({ table: c.table, row: n })}>{n}</span>
                ))}
                {c.names.length > 40 && <span className="text-xs text-zinc-500">+{c.names.length - 40} more</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      {detail.paths.length > 0 && (
        <div>
          <h4 className={h4}>Files</h4>
          <div className="kv">
            {detail.paths.map((p) => (
              <Fragment key={p.column}>
                <span className="k">{p.column}</span>
                <span className="v">
                  <span className="font-mono text-[11px]" title={p.path}>{basename(p.path)}</span>{' '}
                  {!p.exists ? (
                    <span className="text-zinc-400">(not found)</span>
                  ) : p.kind === 'structure' ? (
                    <span className={link} onClick={() => onViewStructure(p.path, p.column)}>view</span>
                  ) : p.kind === 'text' ? (
                    <span className={link} onClick={() => setTextPath(textPath === p.path ? null : p.path)}>text</span>
                  ) : null}
                </span>
              </Fragment>
            ))}
          </div>
          {textPath && <div className="mt-2"><FileView path={textPath} /></div>}
        </div>
      )}
      <div>
        <h4 className={h4}>{detail.table}</h4>
        <Fields row={detail.row} keys={own} />
      </div>
      {ancestors.map(([source, keys]) => {
        const ks = present(keys)
        return ks.length ? (
          <details key={source} className="group">
            <summary className={h4 + ' cursor-pointer list-none'}>
              <span className="mr-1 inline-block transition-transform group-open:rotate-90">▸</span>
              {source} <span className="font-normal text-zinc-400">({ks.length})</span>
            </summary>
            <Fields row={detail.row} keys={ks} />
          </details>
        ) : null
      })}
    </div>
  )
}
