export type Cell = string | number | boolean | null

export type Leaf = {
  name: string
  tool: string
  dir_label: string
  kind: 'create' | 'update' | 'merge'
  status: 'reserved' | 'submitted' | 'collected'
  meta: Record<string, unknown> | null
  tasks: { n: number; ok: number; failed: number; pending: number; executor: string | null }
  rows: { ok: number; other: number } | null
}

export type TableNode = {
  name: string
  gen: number | null
  label: string
  parent: string | null
  tool: string | null
  created_at: string | null
  registered: boolean
  collected: boolean
  n_rows: number | null
  mtime: number | null
  sources: string[]
  leaves: Leaf[]
}

export type Edge = { from: string; to: string; kind: 'parent' | 'merge' }
export type Tree = { run_dir: string; name: string; tables: TableNode[]; edges: Edge[] }

export type ColumnMeta = {
  name: string
  source: string
  is_numeric: boolean
  n_non_null: number
  min?: number
  max?: number
  n_unique?: number
  is_path?: boolean
}

export type Frame = { names: string[]; cols: Cell[][] }

export type TableData = {
  table: string
  joined: boolean
  n_rows: number
  columns: ColumnMeta[]
  data: Frame
  warning?: string
}

export type RowRef = { table: string; name: string; row: Record<string, Cell> }
export type PathRef = { column: string; path: string; kind: 'structure' | 'text' | 'other'; exists: boolean }
export type RowDetail = {
  table: string
  name: string
  row: Record<string, Cell>
  lineage: RowRef[]
  children: { table: string; names: string[] }[]
  paths: PathRef[]
}

export type Task = { id: string; exit: number | null; out: string; err: string | null }
export type LeafDetail = {
  meta: Record<string, unknown> | null
  tasks: Task[]
  files: { name: string; is_dir: boolean; size: number | null; path: string }[]
}

export type FileText = { path: string; text: string; truncated: boolean }

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

const q = (params: Record<string, string>) => new URLSearchParams(params).toString()

export const api = {
  tree: () => getJSON<Tree>('api/tree'),
  table: (table: string, joined: boolean) =>
    getJSON<TableData>(`api/tables/${encodeURIComponent(table)}?joined=${joined}`),
  row: (table: string, name: string) =>
    getJSON<RowDetail>(`api/tables/${encodeURIComponent(table)}/rows/${encodeURIComponent(name)}`),
  leaf: (table: string, leaf: string) =>
    getJSON<LeafDetail>(`api/leaves/${encodeURIComponent(table)}/${encodeURIComponent(leaf)}`),
  file: (path: string) => getJSON<FileText>(`api/file?${q({ path })}`),
  structureUrl: (path: string) => `api/structure?${q({ path })}`,
}
