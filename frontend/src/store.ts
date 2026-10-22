import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type PlotType = 'scatter' | 'histogram' | 'box' | 'violin' | 'heatmap'
export type Filter = { id: number; col: string; min?: number | null; max?: number | null; values?: string[]; text?: string }
export type Sort = { col: string | null; dir: 1 | -1 }
export type View = {
  x?: string
  y?: string
  color?: string
  pathCol?: string
  plotType: PlotType
  bins: number
  filters: Filter[]
  filterMode: 'any' | 'all'
  sort: Sort
  search: string
  allCols: boolean
  tableCollapsed: boolean
  showFilters: boolean
}

export const defaultView: View = {
  plotType: 'scatter',
  bins: 30,
  filters: [],
  filterMode: 'all',
  sort: { col: null, dir: 1 },
  search: '',
  allCols: false,
  tableCollapsed: false,
  showFilters: false,
}

type Store = {
  views: Record<string, View>
  selection: Record<string, string[]>
  treeOpen: boolean
  setView: (key: string, patch: Partial<View>) => void
  setSelection: (key: string, names: string[]) => void
  toggleTree: () => void
}

export const useStore = create<Store>()(
  persist(
    (set) => ({
      views: {},
      selection: {},
      treeOpen: true,
      setView: (key, patch) =>
        set((s) => ({ views: { ...s.views, [key]: { ...defaultView, ...s.views[key], ...patch } } })),
      setSelection: (key, names) => set((s) => ({ selection: { ...s.selection, [key]: names } })),
      toggleTree: () => set((s) => ({ treeOpen: !s.treeOpen })),
    }),
    { name: 'prosapia' },
  ),
)

export const viewKey = (run: string, table: string) => `${run}::${table}`
