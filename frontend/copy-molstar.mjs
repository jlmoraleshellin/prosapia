// Mol* ships a prebuilt viewer bundle; it is served next to the app instead of
// being imported, so Vite never has to compile molstar's sources.
import { copyFileSync, mkdirSync } from 'node:fs'

mkdirSync('public/molstar', { recursive: true })
for (const f of ['molstar.js', 'molstar.css']) {
  copyFileSync(`node_modules/molstar/build/viewer/${f}`, `public/molstar/${f}`)
}
