import { hierarchy, tree } from 'd3-hierarchy'
import { useMemo } from 'react'
import type { Leaf, TableNode, Tree } from '../api'
import { setRoute } from '../route'

type Datum = { node: TableNode | null; children: Datum[] }

const W = 184
const LEAF_H = 19
const PAD = 20
const GAP_X = 44

function nodeHeight(n: TableNode) {
  return 46 + n.leaves.length * LEAF_H + (n.leaves.length ? 4 : 0)
}

export default function TreeView({ tree: t, table, leaf }: { tree: Tree; table?: string; leaf?: string }) {
  const layout = useMemo(() => {
    const byName = new Map(t.tables.map((n) => [n.name, { node: n, children: [] as Datum[] }]))
    const roots: Datum[] = []
    for (const d of byName.values()) {
      const parent = d.node!.parent ? byName.get(d.node!.parent) : undefined
      ;(parent ? parent.children : roots).push(d)
    }
    const maxH = Math.max(60, ...t.tables.map(nodeHeight))
    const root = tree<Datum>().nodeSize([maxH + 16, W + GAP_X])(hierarchy<Datum>({ node: null, children: roots }))
    const nodes = root.descendants().filter((d) => d.data.node)
    // d3 lays the tree top-down; swap the axes so generations run left to right,
    // and drop the synthetic root's column.
    const pos = new Map(nodes.map((d) => [d.data.node!.name, { x: d.y - W - GAP_X, y: d.x }]))
    const ys = [...pos.values()].map((p) => p.y)
    const minY = Math.min(0, ...ys) - maxH / 2
    const maxY = Math.max(0, ...ys) + maxH / 2
    const maxX = Math.max(0, ...[...pos.values()].map((p) => p.x)) + W
    return { pos, minY, width: maxX + PAD * 2, height: maxY - minY + PAD * 2 }
  }, [t])

  const heights = useMemo(() => new Map(t.tables.map((n) => [n.name, nodeHeight(n)])), [t])
  const at = (name: string) => {
    const p = layout.pos.get(name)!
    return { x: p.x + PAD, y: p.y - layout.minY + PAD }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-auto">
        <svg width={layout.width} height={layout.height} className="tree">
          {t.edges.map((e) => {
            if (!layout.pos.has(e.from) || !layout.pos.has(e.to)) return null
            const a = at(e.from)
            const b = at(e.to)
            const x1 = a.x + W
            const x2 = b.x
            const mx = (x1 + x2) / 2
            return (
              <path
                key={`${e.kind}:${e.from}>${e.to}`}
                className={`edge ${e.kind}`}
                d={`M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`}
              />
            )
          })}
          {t.tables.map((n) => {
            const p = at(n.name)
            const h = heights.get(n.name)!
            const selected = n.name === table
            const cls = ['node drop-shadow-sm', selected && 'selected', !n.collected && 'pending', n.tool === 'merge' && 'merge']
            return (
              <g
                key={n.name}
                transform={`translate(${p.x},${p.y - h / 2})`}
                className={cls.filter(Boolean).join(' ')}
                onClick={() => setRoute({ table: n.name })}
              >
                <rect width={W} height={h} rx={10} />
                <text x={12} y={19} className="node-name">
                  {n.name}
                </text>
                <text x={W - 12} y={19} className="node-meta font-mono">
                  {n.gen !== null ? `g${n.gen}` : ''}
                </text>
                <text x={12} y={35} className="node-meta">
                  {n.collected ? `${n.n_rows} rows` : n.registered ? 'not collected' : ''}
                  {n.tool ? ` · ${n.tool}` : ''}
                </text>
                {n.leaves.map((l, i) => (
                  <LeafPill key={l.name} leaf={l} y={48 + i * LEAF_H} selected={selected && leaf === l.name} table={n.name} />
                ))}
              </g>
            )
          })}
        </svg>
      </div>
      <div className="flex flex-none items-center gap-3 border-t border-zinc-200 px-3 py-1.5 text-[11px] text-zinc-500">
        <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-emerald-500" /> collected</span>
        <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-amber-400" /> submitted</span>
        <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-zinc-400" /> reserved</span>
        <span className="flex items-center gap-1"><i className="h-0 w-4 border-t border-dashed border-indigo-400" /> merge</span>
      </div>
    </div>
  )
}

function LeafPill({ leaf, y, selected, table }: { leaf: Leaf; y: number; selected: boolean; table: string }) {
  const t = leaf.tasks
  const tasks = t.n ? (t.executor === 'slurm' ? `${t.n} tasks` : `${t.ok}/${t.n}${t.failed ? ` ✗${t.failed}` : ''}`) : ''
  const right = leaf.rows
    ? `${leaf.rows.ok} ok${leaf.rows.other ? ` · ${leaf.rows.other} other` : ''}`
    : tasks || leaf.status
  return (
    <g
      transform={`translate(12,${y})`}
      className={`leaf ${leaf.status} ${selected ? 'selected' : ''}`}
      onClick={(e) => {
        e.stopPropagation()
        setRoute({ table, leaf: leaf.name, row: undefined })
      }}
    >
      <rect x={-4} y={-1} width={W - 16} height={LEAF_H - 3} rx={5} />
      <circle cx={5} cy={7} r={3.5} className="dot" />
      <text x={14} y={11} className="leaf-name">
        {leaf.name}
      </text>
      <text x={W - 24} y={11} className="leaf-meta" textAnchor="end">
        {right}
      </text>
    </g>
  )
}
