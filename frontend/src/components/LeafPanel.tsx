import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api } from '../api'
import { badge, h4, link } from '../ui'
import FileView from './FileView'

export default function LeafPanel({ table, leaf }: { table: string; leaf: string }) {
  const q = useQuery({ queryKey: ['leaf', table, leaf], queryFn: () => api.leaf(table, leaf), refetchInterval: 10_000 })
  const [open, setOpen] = useState<string | null>(null)
  if (q.isLoading) return <div className="p-4 text-sm text-zinc-500">loading…</div>
  if (q.error || !q.data) return <div className="p-4 text-sm text-rose-600">{String(q.error)}</div>
  const { meta, tasks, files } = q.data
  const done = tasks.filter((t) => t.exit !== null).length
  return (
    <div className="space-y-4 p-4">
      <div>
        <h3 className="text-base font-semibold tracking-tight text-zinc-900">{leaf}</h3>
        <div className="font-mono text-[11px] text-zinc-500">{table}/{leaf}</div>
      </div>
      {meta && (
        <div>
          <h4 className={h4}>Run parameters</h4>
          <div className="kv">
            {Object.entries(meta).map(([k, v]) => (
              <Fragment key={k}>
                <span className="k">{k}</span>
                <span className="v" title={JSON.stringify(v)}>
                  {v == null ? <span className="text-zinc-300">—</span> : typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </Fragment>
            ))}
          </div>
        </div>
      )}
      {tasks.length > 0 && (
        <div>
          <h4 className={h4}>
            Tasks <span className="font-normal normal-case tracking-normal text-zinc-400">{done}/{tasks.length} finished</span>
          </h4>
          <div className="overflow-hidden rounded-lg border border-zinc-200">
            <table className="w-full text-xs">
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} className="border-b border-zinc-100 last:border-b-0">
                    <td className="px-2.5 py-1.5 font-mono text-[11px]">{t.id}</td>
                    <td className="px-2.5 py-1.5">
                      <span className={badge(t.exit === null ? 'idle' : t.exit === 0 ? 'ok' : 'fail')}>
                        {t.exit === null ? 'no exit status' : t.exit === 0 ? 'ok' : `exit ${t.exit}`}
                      </span>
                    </td>
                    <td className="px-2.5 py-1.5 text-right">
                      <span className={link} onClick={() => setOpen(open === t.out ? null : t.out)}>out</span>
                      {t.err && (
                        <>
                          <span className="mx-1 text-zinc-300">·</span>
                          <span className={link} onClick={() => setOpen(open === t.err ? null : t.err)}>err</span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {open && (
            <div className="mt-2">
              <div className="mb-1 font-mono text-[11px] text-zinc-500">{open}</div>
              <FileView path={open} />
            </div>
          )}
        </div>
      )}
      <details className="group">
        <summary className={h4 + ' cursor-pointer list-none'}>
          <span className="mr-1 inline-block transition-transform group-open:rotate-90">▸</span>
          Files <span className="font-normal text-zinc-400">({files.length})</span>
        </summary>
        <div className="kv">
          {files.map((f) => (
            <Fragment key={f.path}>
              <span className="k font-mono">{f.name}{f.is_dir ? '/' : ''}</span>
              <span className="v text-zinc-400">{f.size != null ? `${f.size} B` : ''}</span>
            </Fragment>
          ))}
        </div>
      </details>
    </div>
  )
}
