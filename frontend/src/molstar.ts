// Mol* is a 4.5 MB prebuilt bundle served beside the app and loaded the first
// time a structure is opened.
export type MolstarViewer = {
  loadStructureFromUrl: (url: string, format: 'pdb' | 'mmcif', isBinary?: boolean, options?: unknown) => Promise<unknown>
  dispose: () => void
  plugin: { clear: () => Promise<void> }
}
type Molstar = { Viewer: { create: (el: HTMLElement, options: Record<string, unknown>) => Promise<MolstarViewer> } }

declare global {
  interface Window {
    molstar?: Molstar
  }
}

let loading: Promise<Molstar> | null = null

export function loadMolstar(): Promise<Molstar> {
  if (window.molstar) return Promise.resolve(window.molstar)
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const css = document.createElement('link')
      css.rel = 'stylesheet'
      css.href = 'molstar/molstar.css'
      const js = document.createElement('script')
      js.src = 'molstar/molstar.js'
      js.onload = () => (window.molstar ? resolve(window.molstar) : reject(new Error('Mol* did not initialise')))
      js.onerror = () => {
        loading = null
        reject(new Error('could not load the Mol* viewer'))
      }
      document.head.append(css, js)
    })
  }
  return loading
}

export function structureFormat(path: string): 'pdb' | 'mmcif' {
  const lower = path.toLowerCase().replace(/\.gz$/, '')
  return lower.endsWith('.cif') || lower.endsWith('.mmcif') || lower.endsWith('.bcif') ? 'mmcif' : 'pdb'
}
