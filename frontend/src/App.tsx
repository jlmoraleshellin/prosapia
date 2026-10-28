import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, type TableNode, type Tree } from './api'
import { col, download, filterRows, sortRows, toTSV } from './frame'
import { categoricalCols, defaultTable, numericCols, pathCols, pickDefaults, withData } from './heuristics'
import { setRoute, useRoute, type Route } from './route'
import { defaultView, useStore, viewKey, type PlotType } from './store'
import { bar, btn, btnGhost, btnPrimary, chip, empty, input, label, select } from './ui'
import FilterPanel from './components/FilterPanel'
import LeafPanel from './components/LeafPanel'
import PlotPanel from './components/PlotPanel'
import RowDetail from './components/RowDetail'
import PathPicker from './components/PathPicker'
import StructureViewer, { type Item } from './components/StructureViewer'
import TableView from './components/TableView'
import TreeView from './components/TreeView'

export default function App() {
  const route = useRoute()
  const treeQ = useQuery({ queryKey: ['tree'], queryFn: api.tree, refetchInterval: 10_000 })
  const tree = treeQ.data
  const { treeOpen, toggleTree } = useStore()

  useEffect(() => {
    if (tree && (!route.table || !tree.tables.some((t) => t.name === route.table))) {
      const t = defaultTable(tree)
      if (t) setRoute({ table: t })
    }
  }, [tree, route.table])

  const node = tree?.tables.find((t) => t.name === route.table)
  // The inspector takes 40vw, so the tree yields room while a design or tool run is open.
  const treeMax = route.row || route.leaf ? 'max-w-[22vw]' : 'max-w-[42vw]'
  return (
    <div className="grid h-screen grid-rows-[auto_1fr]">
      <header className="flex h-12 flex-none items-center gap-3 border-b border-zinc-200 bg-white px-3">
        <button className={btnGhost} onClick={toggleTree} title="Toggle the workflow tree">☰</button>
        <span className="flex items-center gap-2">
          <span className="h-5 w-5 rounded-md bg-linear-to-br from-indigo-500 to-violet-600 shadow-sm" />
          <span className="font-semibold tracking-tight">prosapia</span>
        </span>
        <span className="rounded-md bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600" title={tree?.run_dir}>{tree?.name ?? '…'}</span>
        {tree && (
          <select className={select} value={route.table ?? ''} onChange={(e) => setRoute({ table: e.target.value })}>
            {tree.tables.map((t) => (
              <option key={t.name} value={t.name} disabled={!t.collected}>
                {t.name}{t.collected ? '' : ' (not collected)'}
              </option>
            ))}
          </select>
        )}
        <span className="flex-1" />
        {treeQ.error && <span className="text-xs text-rose-600">{String(treeQ.error)}</span>}
      </header>
      <div className="grid min-h-0 grid-cols-[auto_1fr_auto]">
        <aside className={`${treeOpen ? treeMax : 'w-0'} min-h-0 overflow-hidden border-r border-zinc-200 bg-zinc-50`}>
          {treeOpen && tree && <TreeView tree={tree} table={route.table} leaf={route.leaf} />}
        </aside>
        {tree && node ? <RunView tree={tree} node={node} route={route} /> : <div className={empty}>{treeQ.isLoading ? 'Loading…' : 'No tables in this run_dir yet.'}</div>}
      </div>
    </div>
  )
}

function RunView({ tree, node, route }: { tree: Tree; node: TableNode; route: Route }) {
  const key = viewKey(tree.name, node.name)
  const view = useStore((s) => s.views[key] ?? defaultView)
  const selection = useStore((s) => s.selection[key] ?? [])
  const { setView, setSelection } = useStore()
  const onView = (patch: Partial<typeof view>) => setView(key, patch)

  const tableQ = useQuery({
    queryKey: ['table', node.name, route.joined],
    queryFn: () => api.table(node.name, route.joined),
    enabled: node.collected,
  })
  const data = tableQ.data
  const columns = data?.columns ?? []
  const frame = data?.data

  // Defaults the first time a table is opened, or when a remembered column is gone.
  useEffect(() => {
    if (!columns.length) return
    const have = (n?: string) => n && columns.some((c) => c.name === n && c.n_non_null > 0)
    const d = pickDefaults(columns)
    const patch: Partial<typeof view> = {}
    if (!have(view.x)) patch.x = d.x
    if (!have(view.y)) patch.y = d.y
    if (view.color && !have(view.color)) patch.color = undefined
    if (!have(view.pathCol)) patch.pathCol = d.pathCol
    if (Object.keys(patch).length) onView(patch)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns])

  const rows = useMemo(() => (frame ? sortRows(frame, filterRows(frame, view.filters, view.search), view.sort) : []), [frame, view.filters, view.search, view.sort])
  const names = useMemo(() => (frame ? (col(frame, 'name') ?? []).map(String) : []), [frame])
  const selected = useMemo(() => new Set(selection), [selection])
  const toggleSelect = (name: string) => setSelection(key, selected.has(name) ? selection.filter((n) => n !== name) : [...selection, name])

  const rowQ = useQuery({
    queryKey: ['row', node.name, route.row],
    queryFn: () => api.row(node.name, route.row!),
    enabled: !!route.row,
  })

  const [compare, setCompare] = useState<{ items: Item[]; mode: 'overlay' | 'split' } | null>(null)
  const [override, setOverride] = useState<Item | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [showDetail, setShowDetail] = useState(true)
  useEffect(() => setOverride(null), [route.row])
  useEffect(() => setCompare(null), [node.name])

  const pathOf = (name: string) => {
    const i = names.indexOf(name)
    const v = frame && view.pathCol ? col(frame, view.pathCol)?.[i] : null
    return typeof v === 'string' && v ? v : null
  }
  const items: Item[] = compare ? compare.items : override ? [override] : route.row && pathOf(route.row) ? [{ path: pathOf(route.row)!, label: route.row }] : []
  const pos = route.row ? rows.findIndex((i) => names[i] === route.row) : -1
  const step = (d: number) => {
    const next = rows[pos + d]
    if (next !== undefined) setRoute({ row: names[next] })
  }
  const compareSelected = (mode: 'overlay' | 'split') => {
    const its = selection.map((n) => ({ path: pathOf(n), label: n })).filter((i): i is Item => !!i.path)
    if (its.length) setCompare({ items: its, mode })
  }
  const structurePaths = rowQ.data?.paths.filter((p) => p.kind === 'structure' && p.exists) ?? []
  const compareColumns = (cols: string[], mode: 'overlay' | 'split') => {
    const its = structurePaths.filter((p) => cols.includes(p.column)).map((p) => ({ path: p.path, label: p.column }))
    if (its.length) setCompare({ items: its, mode })
  }
  const showInspector = !!route.leaf || !!route.row || !!compare
  const visibleCols = withData(columns).filter((c) => c.name !== 'name' && (view.allCols || c.source === 'own' || [view.x, view.y, view.color, view.pathCol].includes(c.name)))
  const nums = numericCols(columns)
  const cats = categoricalCols(columns)
  const paths = pathCols(columns)
  const sel = (id: string, text: string, value: string | undefined, opts: { name: string }[], onChange: (v?: string) => void, none?: string) => (
    <span className="inline-flex items-center gap-1.5">
      <label className={label} htmlFor={id}>{text}</label>
      <select id={id} className={select} value={value ?? ''} onChange={(e) => onChange(e.target.value || undefined)}>
        {none && <option value="">{none}</option>}
        {opts.map((o) => (
          <option key={o.name} value={o.name}>{o.name}</option>
        ))}
      </select>
    </span>
  )
  const isDist = view.plotType === 'box' || view.plotType === 'violin'

  return (
    <>
      <div className="flex min-h-0 min-w-0 flex-col bg-white">
        <div className={bar}>
          <select className={select} value={view.plotType} onChange={(e) => onView({ plotType: e.target.value as PlotType })}>
            <option value="scatter">Scatter</option>
            <option value="histogram">Histogram</option>
            <option value="box">Box</option>
            <option value="violin">Violin</option>
            <option value="heatmap">2D heatmap</option>
          </select>
          {!isDist && sel('x', 'x', view.x, nums, (x) => onView({ x }))}
          {view.plotType !== 'histogram' && sel('y', 'y', view.y, nums, (y) => onView({ y }))}
          {sel('color', view.plotType === 'scatter' ? 'color' : 'group', view.color, view.plotType === 'scatter' ? withData(columns) : cats, (color) => onView({ color }), '— none —')}
          {(view.plotType === 'histogram' || view.plotType === 'heatmap') && (
            <span className="inline-flex items-center gap-1.5">
              <label className={label}>bins</label>
              <input className={input + ' w-16'} type="number" value={view.bins} min={2} onChange={(e) => onView({ bins: Number(e.target.value) || 30 })} />
            </span>
          )}
          {sel('path', 'structure', view.pathCol, paths, (pathCol) => onView({ pathCol }), '— none —')}
          <span className="flex-1" />
          <input className={input + ' w-44'} type="search" placeholder="Find design…" value={view.search} onChange={(e) => onView({ search: e.target.value })} />
          <button className={view.filters.length ? btnPrimary : btn} onClick={() => onView({ showFilters: !view.showFilters })}>
            Filters{view.filters.length ? ` · ${view.filters.length}` : ''}
          </button>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-zinc-600" title="Join every ancestor table's columns">
            <input type="checkbox" className="accent-indigo-600" checked={route.joined} onChange={(e) => setRoute({ joined: e.target.checked })} /> lineage
          </label>
        </div>
        {data?.warning && <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">{data.warning}</div>}
        {!node.collected ? (
          <div className={empty}>{node.name} is registered but not collected yet.</div>
        ) : !frame ? (
          <div className={empty}>{tableQ.error ? String(tableQ.error) : 'Loading…'}</div>
        ) : (
          <div className="flex min-h-0 flex-1">
            {view.showFilters && <FilterPanel frame={frame} columns={columns} view={view} onView={onView} />}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <PlotPanel frame={frame} columns={columns} rows={rows} view={view} current={route.row} selected={selected} onPick={(row) => setRoute({ row })} onSelect={(ns) => setSelection(key, ns)} />
              <section className={`flex flex-none flex-col border-t border-zinc-200 ${view.tableCollapsed ? '' : 'h-[38vh]'}`}>
                <div className="flex flex-none items-center gap-2 bg-zinc-50/70 px-3 py-1.5">
                  <button className={btnGhost + ' h-6 w-6'} onClick={() => onView({ tableCollapsed: !view.tableCollapsed })}>{view.tableCollapsed ? '▸' : '▾'}</button>
                  <span className="text-xs font-semibold">{node.name}</span>
                  <span className="text-xs text-zinc-500">
                    {rows.length === data!.n_rows ? `${rows.length} rows` : `${rows.length} of ${data!.n_rows} rows`} · {columns.length} columns
                  </span>
                  <span className="flex-1" />
                  <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-zinc-600">
                    <input type="checkbox" className="accent-indigo-600" checked={view.allCols} onChange={(e) => onView({ allCols: e.target.checked })} /> all columns
                  </label>
                  <button className={btn} onClick={() => download(toTSV(frame, rows, ['name', ...visibleCols.map((c) => c.name)]), `${node.name}_${rows.length}.tsv`, 'text/tab-separated-values')}>Export TSV</button>
                </div>
                {!view.tableCollapsed && (
                  <TableView frame={frame} columns={visibleCols} rows={rows} sort={view.sort} onSort={(sort) => onView({ sort })} current={route.row} selected={selected} onToggleSelect={toggleSelect} onPick={(row) => setRoute({ row })} />
                )}
              </section>
            </div>
          </div>
        )}
        {selection.length > 0 && (
          <div className="flex flex-none flex-wrap items-center gap-2 border-t border-indigo-100 bg-indigo-50/60 px-3 py-2">
            <span className="text-xs font-semibold text-indigo-700">{selection.length} selected</span>
            <div className="flex flex-wrap gap-1">
              {selection.slice(0, 30).map((n) => (
                <span className={chip + ' bg-white'} key={n}>
                  <span className="cursor-pointer" onClick={() => setRoute({ row: n })}>{n}</span>
                  <span className="cursor-pointer text-indigo-300 hover:text-pink-600" onClick={() => toggleSelect(n)}>×</span>
                </span>
              ))}
              {selection.length > 30 && <span className="text-xs text-zinc-500">+{selection.length - 30}</span>}
            </div>
            <span className="flex-1" />
            <button className={btnPrimary} onClick={() => compareSelected('overlay')} disabled={!view.pathCol}>Overlay</button>
            <button className={btn} onClick={() => compareSelected('split')} disabled={!view.pathCol}>Split</button>
            <button className={btn} onClick={() => setSelection(key, [])}>Clear</button>
          </div>
        )}
      </div>
      {showInspector && (
        <aside className={'flex min-h-0 flex-col bg-white ' + (expanded ? 'fixed inset-0 z-40' : 'w-[40vw] min-w-[380px] max-w-[900px] border-l border-zinc-200')}>
          <div className={bar + ' h-12'}>
            {route.leaf ? (
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Tool run</span>
            ) : (
              <>
                <span className="font-semibold">{compare ? `Comparing ${compare.items.length}` : route.row}</span>
                {!compare && route.row && pos >= 0 && (
                  <span className="inline-flex items-center gap-1">
                    <button className={btnGhost} onClick={() => step(-1)} disabled={pos <= 0} title="Previous (in table order)">‹</button>
                    <span className="text-xs tabular-nums text-zinc-500">{pos + 1} / {rows.length}</span>
                    <button className={btnGhost} onClick={() => step(1)} disabled={pos >= rows.length - 1} title="Next">›</button>
                  </span>
                )}
              </>
            )}
            <span className="flex-1" />
            {compare ? (
              <button className={btn} onClick={() => setCompare(null)}>Back</button>
            ) : (
              route.row && structurePaths.length > 1 && <PathPicker key={route.row} paths={structurePaths} shown={items[0]?.path} onCompare={compareColumns} />
            )}
            {!route.leaf && (
              <button className={btnGhost} onClick={() => setExpanded(!expanded)} title={expanded ? 'Show the data again' : 'Fill the window'}>
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  {expanded ? <path d="M6 2v4H2M10 2v4h4M6 14v-4H2M10 14v-4h4" /> : <path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4" />}
                </svg>
              </button>
            )}
            <button className={btnGhost} onClick={() => { setCompare(null); setRoute({ row: undefined, leaf: undefined }) }} title="Close">×</button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-auto">
            {route.leaf ? (
              <LeafPanel table={node.name} leaf={route.leaf} />
            ) : (
              <>
                {items.length > 0 && <StructureViewer items={items} mode={compare?.mode ?? 'overlay'} />}
                {!compare && route.row && rowQ.data && (
                  <>
                    {items.length > 0 && (
                      <button className="flex flex-none items-center gap-1 border-b border-zinc-200 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 hover:bg-zinc-50" onClick={() => setShowDetail(!showDetail)}>
                        <span className={'inline-block transition-transform ' + (showDetail ? 'rotate-90' : '')}>▸</span> Details
                      </button>
                    )}
                    {(showDetail || items.length === 0) && (
                      <RowDetail detail={rowQ.data} columns={columns} onViewStructure={(path, label) => setOverride({ path, label })} />
                    )}
                  </>
                )}
                {!compare && route.row && rowQ.error && <div className={empty}>{String(rowQ.error)}</div>}
              </>
            )}
          </div>
        </aside>
      )}
    </>
  )
}
