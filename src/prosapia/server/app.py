"""The read-only HTTP API behind ``sapia serve``, plus the built frontend."""

import gzip
from pathlib import Path
from typing import Sequence

from ..core.naming import PARENT_NAME, PARENT_TABLE
from .paths import is_structure, is_text, resolve_safe_path, structure_media_type
from .tables import load_raw, load_table, open_run, row_dict, table_names
from .tree import build_tree, list_tasks, read_meta

STATIC_DIR = Path(__file__).parent / "static"
FILE_CAP = 256 * 1024


def build_app(run_dir: Path, roots: Sequence[Path] = ()):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles

    run_dir = run_dir.resolve()
    roots = [r.resolve() for r in roots]
    cache, dm = open_run(run_dir)

    app = FastAPI(title="prosapia")
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    def require_table(table: str) -> None:
        if table not in table_names(cache, dm):
            raise HTTPException(404, f"unknown table: {table}")

    def resolve(raw: str) -> Path:
        try:
            return resolve_safe_path(raw, run_dir, roots)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))

    @app.get("/api/tree")
    def api_tree():
        return build_tree(cache, dm)

    @app.get("/api/tables/{table}")
    def api_table(table: str, joined: bool = True):
        require_table(table)
        df, columns, data = load_table(cache, dm, table, joined)
        out = {
            "table": table,
            "joined": joined,
            "n_rows": len(df),
            "columns": columns,
            "data": data,
        }
        if cache.stale:
            out["warning"] = (
                "being written, showing the last readable copy: "
                + ", ".join(sorted(cache.stale))
            )
        return out

    @app.get("/api/tables/{table}/rows/{name}")
    def api_row(table: str, name: str):
        require_table(table)
        df, _, _ = load_table(cache, dm, table, True)
        hits = df.index[df["name"] == name] if "name" in df.columns else []
        if not len(hits):
            raise HTTPException(404, f"unknown row: {table}/{name}")
        row = row_dict(df, int(hits[0]))
        lineage = []
        for anc_table, anc_name in dm.trace_lineage(table, name):
            anc = load_raw(cache, anc_table)
            anc_row = row_dict(anc.reset_index(), int(anc.index.get_loc(anc_name))) if anc_name in anc.index else {}
            lineage.append({"table": anc_table, "name": anc_name, "row": anc_row})
        children = []
        for other in table_names(cache, dm):
            f = load_raw(cache, other)
            if PARENT_NAME in f.columns and PARENT_TABLE in f.columns:
                names = [str(n) for n in f.index[(f[PARENT_TABLE] == table) & (f[PARENT_NAME] == name)]]
                if names:
                    children.append({"table": other, "names": names})
        paths = []
        for col, v in row.items():
            if not isinstance(v, str) or not v:
                continue
            kind = "structure" if is_structure(v) else "text" if is_text(v) else None
            if kind is None and not col.endswith("_path"):
                continue
            try:
                resolve_safe_path(v, run_dir, roots)
                exists = True
            except (FileNotFoundError, PermissionError):
                exists = False
            paths.append({"column": col, "path": v, "kind": kind or "other", "exists": exists})
        return {"table": table, "name": name, "row": row, "lineage": lineage, "children": children, "paths": paths}

    @app.get("/api/leaves/{table}/{leaf}")
    def api_leaf(table: str, leaf: str):
        require_table(table)
        leaf_dir = (run_dir / table / leaf).resolve()
        if not leaf_dir.is_dir() or leaf_dir.parent != run_dir / table:
            raise HTTPException(404, f"unknown tool run: {table}/{leaf}")
        files = []
        for entry in sorted(leaf_dir.iterdir(), key=lambda p: p.name)[:500]:
            files.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                    "path": str(entry.relative_to(run_dir)),
                }
            )
        return {"meta": read_meta(leaf_dir), "tasks": list_tasks(run_dir, leaf_dir), "files": files}

    @app.get("/api/structure")
    def api_structure(path: str = Query(...)):
        resolved = resolve(path)
        if not is_structure(resolved.name):
            raise HTTPException(400, f"not a structure file: {path}")
        media = structure_media_type(resolved.name)
        headers = {"Cache-Control": "private, max-age=600"}
        if resolved.name.lower().endswith(".gz"):
            with gzip.open(resolved, "rb") as f:
                return Response(f.read(), media_type=media, headers=headers)
        return FileResponse(resolved, media_type=media, headers=headers)

    @app.get("/api/file")
    def api_file(path: str = Query(...)):
        resolved = resolve(path)
        if not is_text(resolved.name):
            raise HTTPException(400, f"not a text file: {path}")
        opener = gzip.open if resolved.name.lower().endswith(".gz") else open
        with opener(resolved, "rb") as f:
            data = f.read(FILE_CAP + 1)
        return {
            "path": path,
            "text": data[:FILE_CAP].decode("utf-8", errors="replace"),
            "truncated": len(data) > FILE_CAP,
        }

    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:
        print(f"[serve] no frontend bundle at {STATIC_DIR}; serving the API only")

    return app
