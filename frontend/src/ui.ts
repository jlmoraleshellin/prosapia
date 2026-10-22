// Shared class strings: one look for every control.
export const btn =
  'inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-md border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 shadow-sm transition-colors hover:border-zinc-300 hover:bg-zinc-50 disabled:pointer-events-none disabled:opacity-40'
export const btnPrimary =
  'inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-md bg-indigo-600 px-2.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-indigo-500 disabled:pointer-events-none disabled:opacity-40'
export const btnGhost =
  'inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 disabled:pointer-events-none disabled:opacity-40'
export const input =
  'h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs text-zinc-800 shadow-sm focus:border-indigo-400 focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20'
export const select = input + ' max-w-[220px] pr-6'
export const label = 'text-[11px] font-medium text-zinc-500'
export const h4 = 'mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500'
export const chip =
  'inline-flex items-center gap-1 rounded-full border border-indigo-100 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700'
export const link = 'cursor-pointer text-indigo-600 hover:underline'
export const bar = 'flex flex-none flex-wrap items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2'
export const empty = 'p-6 text-sm text-zinc-500'
export const badge = (tone: 'ok' | 'fail' | 'idle') =>
  'rounded-full px-1.5 py-0.5 text-[11px] font-medium ' +
  { ok: 'bg-emerald-50 text-emerald-700', fail: 'bg-rose-50 text-rose-700', idle: 'bg-zinc-100 text-zinc-500' }[tone]
