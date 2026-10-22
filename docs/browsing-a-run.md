# Browsing a run

`sapia serve` opens a run_dir in the browser: the workflow tree, every table with
its lineage joined in, plots, and a Mol* structure viewer. It is read-only.

```bash
uv sync --group ui                      # once: fastapi + uvicorn (or: pip install fastapi uvicorn)
sapia serve outputs/20260915_demo       # opens http://127.0.0.1:8765/
sapia serve "$RUN_DIR" --port 9000 --no-browser
```

On an HPC login node, forward the port and open it on your laptop:

```bash
ssh -L 8765:127.0.0.1:8765 user@login.node
```

## What you see

- **Tree (left).** One node per table in the registry, laid out by generation,
  with `parent_table` edges and dashed edges from a merge's sources. Each node lists
  the tool runs found under `run_dir/<table>/<leaf>/` with a status inferred from
  disk: *reserved* (registered by `sapia run`, nothing ran yet), *submitted* (task
  logs exist, not collected) or *collected* (the table, or a `<leaf>_status`
  column, exists). Task counts come from the executors' `.exit` files; SLURM writes
  none, so its runs show a task count only. Click a node to open its table, a tool
  run to see its parameters, tasks and logs. The tree refreshes every 10 s.
- **Table (centre).** By default the table is joined with its ancestors
  (`DataManager.join_lineage`), so a sequence table also shows the backbone's
  scores and structure path; untick *lineage* for the table's own columns. Columns
  from an ancestor carry that table's name in the header. Sort by clicking a header,
  search by design name, add numeric or categorical filters, export the filtered
  rows as TSV. The table lists at most 300 rows; plots and export use all of them.
- **Plot.** Scatter, histogram, box, violin or 2D heatmap over the filtered rows.
  Click a point to open that design; lasso to select several.
- **Design (right).** The row's values grouped by table, its ancestors (click to
  walk up), its children in later tables, and its files. Structure columns
  (`*.pdb`, `*.cif`, gzipped or not) open in Mol*; `‹ ›` steps through the table in
  its current order. *Overlay columns* loads every structure column of the row
  into one viewer; the selection bar's *Overlay* / *Split* compares selected
  designs.

View settings (axes, filters, sort, selection) are remembered per table in the
browser.

## Paths

Tables store paths as `sapia` built them: relative to where it ran (usually the
repo root, `outputs/<run>/...`) or absolute. The server resolves relative paths
against the run_dir and its parents and only serves files under the run_dir.
Tables holding absolute paths elsewhere (a hand-made seed table) need those
directories passed with `--roots`:

```bash
sapia serve "$RUN_DIR" --roots /data/seeds
```

A run pulled from the Modal Volume stores paths under `/runs/...`; serve it from a
directory mounted or copied to `/runs`, or pass `--roots`.

## Developing the frontend

The UI is a React + Vite app in `frontend/`, styled with Tailwind, built into
`src/prosapia/server/static/`, which is committed so an install from git needs no
Node. Developing it needs Node 20.19+ (`frontend/.nvmrc` pins 20, so `nvm use`
in that directory picks it). After changing `frontend/`:

```bash
cd frontend && nvm use
npm install
npm run build      # type-checks, then writes src/prosapia/server/static/
```

and commit `static/` with the change. For live reloading run `sapia serve ...
--no-browser` and `npm run dev`, which proxies `/api` to it.
