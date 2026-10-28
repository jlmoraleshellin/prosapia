import { useState } from 'react'
import type { PathRef } from '../api'
import { basename } from '../frame'
import { btn, btnPrimary, select } from '../ui'

type Mode = 'overlay' | 'split'

// Pick which of a row's structure columns to compare; nothing is picked by default.
export default function PathPicker({ paths, shown, onCompare }: { paths: PathRef[]; shown?: string; onCompare: (cols: string[], mode: Mode) => void }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [mode, setMode] = useState<Mode>('overlay')
  const toggle = (c: string) => setPicked(picked.includes(c) ? picked.filter((x) => x !== c) : [...picked, c])
  return (
    <span className="relative">
      <button className={open ? btnPrimary : btn} onClick={() => setOpen(!open)} title="Compare this design across structure columns">
        Compare paths ({paths.length})
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-20 w-80 rounded-md border border-zinc-200 bg-white p-2 shadow-lg">
          {paths.map((p) => (
            <label key={p.column} className="flex cursor-pointer items-center gap-2 py-1 text-xs">
              <input type="checkbox" className="accent-indigo-600" checked={picked.includes(p.column)} onChange={() => toggle(p.column)} />
              <span className="font-medium text-zinc-700">{p.column}</span>
              {p.path === shown && <span className="rounded-full bg-indigo-50 px-1.5 text-[10px] text-indigo-600">shown</span>}
              <span className="ml-auto max-w-[140px] truncate text-[10px] text-zinc-400" title={p.path}>{basename(p.path)}</span>
            </label>
          ))}
          <div className="mt-2 flex items-center gap-2 border-t border-zinc-100 pt-2">
            <select className={select} value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              <option value="overlay">Overlay</option>
              <option value="split">Split</option>
            </select>
            <span className="flex-1" />
            <button className={btnPrimary} disabled={!picked.length} onClick={() => { setOpen(false); onCompare(picked, mode) }}>
              Compare{picked.length ? ` (${picked.length})` : ''}
            </button>
          </div>
        </div>
      )}
    </span>
  )
}
