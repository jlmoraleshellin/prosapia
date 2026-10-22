import { useEffect, useRef } from 'react'
import type { Cell, ColumnMeta, Frame } from '../api'
import { col, fmt } from '../frame'
import type { View } from '../store'

type PlotlyLib = typeof import('plotly.js')
let plotly: Promise<PlotlyLib> | null = null
const loadPlotly = () => (plotly ??= import('plotly.js-cartesian-dist-min').then((m: any) => (m.default ?? m) as PlotlyLib))

const MAX_GROUPS = 30

function groups(values: Cell[] | undefined, rows: number[]): Map<string, number[]> {
  const out = new Map<string, number[]>()
  if (!values) return new Map([['', rows]])
  for (const i of rows) {
    const k = values[i] == null ? 'n/a' : String(values[i])
    if (!out.has(k)) out.set(k, [])
    out.get(k)!.push(i)
  }
  if (out.size > MAX_GROUPS) {
    const top = [...out.entries()].sort((a, b) => b[1].length - a[1].length)
    const keep = new Map(top.slice(0, MAX_GROUPS - 1))
    keep.set('other', top.slice(MAX_GROUPS - 1).flatMap(([, r]) => r))
    return keep
  }
  return out
}

export default function PlotPanel({
  frame,
  columns,
  rows,
  view,
  current,
  selected,
  onPick,
  onSelect,
}: {
  frame: Frame
  columns: ColumnMeta[]
  rows: number[]
  view: View
  current?: string
  selected: Set<string>
  onPick: (name: string) => void
  onSelect: (names: string[]) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const handlers = useRef({ onPick, onSelect })
  handlers.current = { onPick, onSelect }

  useEffect(() => {
    const div = ref.current!
    let dead = false
    loadPlotly().then((Plotly) => {
      if (dead) return
      const names = (col(frame, 'name') ?? []).map(String)
      const x = col(frame, view.x)
      const y = col(frame, view.y)
      const c = col(frame, view.color)
      const cMeta = columns.find((m) => m.name === view.color)
      const pick = (vals: Cell[] | undefined, idx: number[]) => idx.map((i) => vals?.[i] ?? null)
      const hover = (idx: number[]) =>
        idx.map((i) => `${names[i]}<br>${view.x}: ${fmt(x?.[i] ?? null)}<br>${view.y}: ${fmt(y?.[i] ?? null)}${c ? `<br>${view.color}: ${fmt(c[i])}` : ''}`)
      const traces: any[] = []
      const type = view.plotType
      const gl = rows.length > 5000
      if (type === 'scatter' && x && y) {
        if (c && cMeta?.is_numeric) {
          traces.push({
            type: gl ? 'scattergl' : 'scatter', mode: 'markers', x: pick(x, rows), y: pick(y, rows), customdata: pick(names, rows),
            text: hover(rows), hoverinfo: 'text', name: '',
            marker: { size: 7, opacity: 0.8, color: pick(c, rows), colorscale: 'Viridis', colorbar: { title: { text: view.color }, thickness: 12 } },
          })
        } else {
          for (const [k, idx] of groups(c, rows)) {
            traces.push({
              type: gl ? 'scattergl' : 'scatter', mode: 'markers', x: pick(x, idx), y: pick(y, idx), customdata: pick(names, idx),
              text: hover(idx), hoverinfo: 'text', name: k || view.x, marker: { size: 7, opacity: 0.8 },
            })
          }
        }
      } else if (type === 'histogram' && x) {
        for (const [k, idx] of groups(c && !cMeta?.is_numeric ? c : undefined, rows)) {
          traces.push({ type: 'histogram', x: pick(x, idx), name: k || view.x, nbinsx: view.bins, opacity: 0.65 })
        }
      } else if ((type === 'box' || type === 'violin') && y) {
        for (const [k, idx] of groups(c && !cMeta?.is_numeric ? c : undefined, rows)) {
          traces.push({ type, y: pick(y, idx), name: k || view.y, boxpoints: 'outliers', points: 'outliers', text: pick(names, idx), customdata: pick(names, idx) })
        }
      } else if (type === 'heatmap' && x && y) {
        traces.push({ type: 'histogram2d', x: pick(x, rows), y: pick(y, rows), nbinsx: view.bins, nbinsy: view.bins, colorscale: 'Viridis' })
      }
      if (type === 'scatter' && x && y) {
        const sel = rows.filter((i) => selected.has(names[i]))
        if (sel.length) traces.push({ type: 'scatter', mode: 'markers', x: pick(x, sel), y: pick(y, sel), customdata: pick(names, sel), hoverinfo: 'skip', name: 'selected', marker: { size: 13, color: 'rgba(0,0,0,0)', line: { color: '#db2777', width: 2 } } })
        const cur = rows.filter((i) => names[i] === current)
        if (cur.length) traces.push({ type: 'scatter', mode: 'markers', x: pick(x, cur), y: pick(y, cur), hoverinfo: 'skip', name: 'viewing', marker: { size: 16, color: 'rgba(0,0,0,0)', line: { color: '#4f46e5', width: 3 } }, showlegend: false })
      }
      const axis = { gridcolor: '#f4f4f5', zerolinecolor: '#e4e4e7', linecolor: '#e4e4e7', tickfont: { size: 11 } }
      const layout: any = {
        margin: { l: 55, r: 20, t: 10, b: 45 },
        paper_bgcolor: '#ffffff',
        plot_bgcolor: '#ffffff',
        font: { family: 'Inter, ui-sans-serif, system-ui, sans-serif', size: 12, color: '#3f3f46' },
        colorway: ['#6366f1', '#ec4899', '#10b981', '#f59e0b', '#0ea5e9', '#8b5cf6', '#ef4444', '#14b8a6', '#f97316', '#64748b'],
        xaxis: { ...axis, title: { text: type === 'box' || type === 'violin' ? '' : view.x } },
        yaxis: { ...axis, title: { text: type === 'histogram' ? 'count' : view.y } },
        barmode: 'overlay',
        dragmode: 'lasso',
        hovermode: 'closest',
        legend: { orientation: 'h', y: 1.05 },
        showlegend: traces.length > 1,
      }
      Plotly.react(div, traces, layout, { responsive: true, displaylogo: false }).then(() => {
        const el = div as any
        el.removeAllListeners?.('plotly_click')
        el.removeAllListeners?.('plotly_selected')
        el.on('plotly_click', (ev: any) => {
          const name = ev.points?.[0]?.customdata
          if (typeof name === 'string') handlers.current.onPick(name)
        })
        el.on('plotly_selected', (ev: any) => {
          const picked = (ev?.points ?? []).map((p: any) => p.customdata).filter((n: unknown) => typeof n === 'string')
          handlers.current.onSelect([...new Set<string>(picked)])
        })
      })
    })
    return () => {
      dead = true
    }
  }, [frame, columns, rows, view.x, view.y, view.color, view.plotType, view.bins, current, selected])

  useEffect(() => {
    const div = ref.current!
    const ro = new ResizeObserver(() => loadPlotly().then((P) => (div as any)._fullLayout && P.Plots.resize(div)))
    ro.observe(div)
    return () => {
      ro.disconnect()
      loadPlotly().then((P) => P.purge(div))
    }
  }, [])

  return <div className="min-h-[200px] flex-1 bg-white" ref={ref} title="Click a point to open it · lasso to select" />
}
