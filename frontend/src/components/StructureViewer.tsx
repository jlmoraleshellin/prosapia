import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { basename } from '../frame'
import { loadMolstar, structureFormat, type MolstarViewer } from '../molstar'

export type Item = { path: string; label: string }

export default function StructureViewer({ items, mode }: { items: Item[]; mode: 'overlay' | 'split' }) {
  const area = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState('')
  const key = items.map((i) => i.path).join('|') + mode

  useEffect(() => {
    const root = area.current!
    const viewers: MolstarViewer[] = []
    let dead = false
    root.innerHTML = ''
    const panels = mode === 'split' ? items.map((i) => [i]) : [items]
    ;(async () => {
      try {
        setStatus('Loading viewer…')
        const ms = await loadMolstar()
        for (const group of panels) {
          if (dead) return
          const panel = document.createElement('div')
          panel.className = 'relative min-w-0 flex-1 border-l border-zinc-200 first:border-l-0'
          const label = document.createElement('div')
          label.className = 'pointer-events-none absolute left-2.5 top-2 z-10 rounded-full bg-zinc-900/60 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm'
          label.textContent = group.map((g) => g.label).join(' + ')
          panel.append(label)
          root.append(panel)
          const viewer = await ms.Viewer.create(panel, {
            layoutIsExpanded: false,
            layoutShowControls: false,
            layoutShowSequence: true,
            layoutShowLog: false,
            layoutShowLeftPanel: false,
            viewportShowExpand: false,
            viewportShowSelectionMode: true,
            viewportShowAnimation: false,
          })
          viewers.push(viewer)
          for (const item of group) {
            if (dead) return
            setStatus(`Loading ${basename(item.path)}…`)
            await viewer.loadStructureFromUrl(api.structureUrl(item.path), structureFormat(item.path), false)
          }
        }
        if (!dead) setStatus(items.map((i) => basename(i.path)).join(', '))
      } catch (err) {
        if (!dead) setStatus(`Failed: ${(err as Error).message ?? err}`)
      }
    })()
    return () => {
      dead = true
      viewers.forEach((v) => {
        try {
          v.dispose()
        } catch {
          /* already gone */
        }
      })
      root.innerHTML = ''
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return (
    <>
      <div className="relative flex min-h-[320px] flex-1 bg-zinc-100" ref={area} />
      <div className="flex-none border-y border-zinc-200 bg-zinc-50 px-3 py-1.5 font-mono text-[11px] text-zinc-500">{status}</div>
    </>
  )
}
