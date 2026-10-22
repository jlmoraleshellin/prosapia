import { useSyncExternalStore } from 'react'

// `#/<table>?row=<name>&leaf=<leaf>&joined=0`: where the user is, shareable.
export type Route = { table?: string; row?: string; leaf?: string; joined: boolean }

export function parseRoute(hash = location.hash): Route {
  const m = /^#\/?([^?]*)(?:\?(.*))?$/.exec(hash)
  const table = m?.[1] ? decodeURIComponent(m[1]) : undefined
  const p = new URLSearchParams(m?.[2] ?? '')
  return {
    table,
    row: p.get('row') ?? undefined,
    leaf: p.get('leaf') ?? undefined,
    joined: p.get('joined') !== '0',
  }
}

export function routeHash(r: Route): string {
  const p = new URLSearchParams()
  if (r.row) p.set('row', r.row)
  if (r.leaf) p.set('leaf', r.leaf)
  if (!r.joined) p.set('joined', '0')
  const qs = p.toString()
  return `#/${encodeURIComponent(r.table ?? '')}${qs ? '?' + qs : ''}`
}

export function setRoute(patch: Partial<Route>) {
  const next = { ...parseRoute(), ...patch }
  if (patch.table !== undefined && patch.table !== parseRoute().table) {
    if (patch.row === undefined) next.row = undefined
    if (patch.leaf === undefined) next.leaf = undefined
  }
  location.hash = routeHash(next)
}

const subscribe = (cb: () => void) => {
  addEventListener('hashchange', cb)
  return () => removeEventListener('hashchange', cb)
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => location.hash)
  return parseRoute(hash)
}
