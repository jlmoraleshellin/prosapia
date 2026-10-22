import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

export default function FileView({ path }: { path: string }) {
  const q = useQuery({ queryKey: ['file', path], queryFn: () => api.file(path) })
  if (q.isLoading) return <div className="text-xs text-zinc-500">loading {path}…</div>
  if (q.error) return <div className="text-xs text-rose-600">{String(q.error)}</div>
  return (
    <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-[11px] leading-relaxed text-zinc-700">
      {q.data!.text || '(empty)'}
      {q.data!.truncated && '\n… truncated'}
    </pre>
  )
}
