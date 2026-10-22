import type { ColumnMeta, Tree } from './api'

// Bookkeeping columns are never a useful default axis; the usual quality metrics
// are preferred, one of each kind first (a pTM, a pLDDT, an RMSD...).
const BOOKKEEPING = /^(gen|name|parent_name|parent_table|merge_source|.*_(iteration|sample|T|n_res|n_chains|seed|model_idx))$/
const METRIC_HINTS = [/i?ptm$/i, /plddt/i, /rmsd/i, /confidence/i, /score/i, /dG/]
const PATH_HINTS = ['relax', 'assembled', 'diffused', 'symm']

export const withData = (cols: ColumnMeta[]) => cols.filter((c) => c.n_non_null > 0)
export const numericCols = (cols: ColumnMeta[]) => withData(cols).filter((c) => c.is_numeric)
export const pathCols = (cols: ColumnMeta[]) => withData(cols).filter((c) => c.is_path)
export const categoricalCols = (cols: ColumnMeta[]) =>
  withData(cols).filter((c) => !c.is_numeric && (c.n_unique ?? 0) <= 50)

export function rankMetrics(cols: ColumnMeta[]): ColumnMeta[] {
  const useful = numericCols(cols).filter((c) => !BOOKKEEPING.test(c.name) && c.min !== c.max)
  const buckets = METRIC_HINTS.map((re) => useful.filter((c) => re.test(c.name)))
  const ranked: ColumnMeta[] = []
  const seen = new Set<string>()
  const add = (c?: ColumnMeta) => {
    if (c && !seen.has(c.name)) {
      seen.add(c.name)
      ranked.push(c)
    }
  }
  const depth = Math.max(0, ...buckets.map((b) => b.length))
  for (let i = 0; i < depth; i++) buckets.forEach((b) => add(b[i]))
  useful.forEach(add)
  return ranked.length ? ranked : numericCols(cols)
}

export function pickPathColumn(cols: ColumnMeta[]): string | undefined {
  const paths = pathCols(cols)
  const own = paths.filter((c) => c.source === 'own')
  for (const hint of PATH_HINTS) {
    const hit = paths.find((c) => c.name.includes(hint))
    if (hit) return hit.name
  }
  return (own[0] ?? paths[0])?.name
}

export function pickDefaults(cols: ColumnMeta[]) {
  const ranked = rankMetrics(cols)
  const x = ranked[0]?.name
  const y = (ranked.find((c) => c.name !== x) ?? numericCols(cols).find((c) => c.name !== x))?.name ?? x
  const color = categoricalCols(cols).find((c) => ['merge_source', 'parent_table'].includes(c.name))?.name
  return { x, y, color, pathCol: pickPathColumn(cols) }
}

// Columns are leaf-prefixed per tool (boltz_ptm, pyrosetta_sasa); ancestor
// columns carry a table prefix (table0__x). Group options by that prefix.
export function colGroup(name: string): string {
  return name.includes('__') ? name.split('__')[0] : name.split('_')[0]
}

const BACKUP = /(backup|\.bak\b|\.pre[_.]|~$)/i

export function defaultTable(tree: Tree): string | undefined {
  const collected = tree.tables.filter((t) => t.collected)
  const main = collected.filter((t) => !BACKUP.test(t.name))
  const pool = main.length ? main : collected
  return pool.sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0))[0]?.name ?? tree.tables[0]?.name
}
