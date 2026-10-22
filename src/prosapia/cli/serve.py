"""``sapia serve`` -- browse a run_dir's lineage, tables and structures in the browser.

    sapia serve RUN_DIR
    sapia serve RUN_DIR --port 9000 --no-browser
    sapia serve RUN_DIR --roots /data/seeds     # structures stored as absolute paths elsewhere
"""

import threading
import webbrowser
from argparse import ArgumentParser, Namespace
from pathlib import Path


class ServeArgs(Namespace):
    run_dir: Path
    host: str
    port: int
    no_browser: bool
    roots: list[Path]


def build_serve_parser() -> ArgumentParser:
    parser = ArgumentParser(add_help=False)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab.")
    parser.add_argument(
        "--roots",
        nargs="*",
        type=Path,
        default=[],
        help="Extra directories files may be served from, for tables holding absolute "
        "paths outside the run_dir.",
    )
    return parser


def serve_from_args(args: ServeArgs) -> None:
    try:
        import uvicorn

        from ..server.app import build_app
    except ImportError:
        raise SystemExit(
            "sapia serve needs fastapi and uvicorn: uv sync --group ui "
            "(or pip install fastapi uvicorn)"
        )
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir() or not any(run_dir.glob("*.tsv")):
        raise SystemExit(f"{run_dir} is not a run_dir (no tables found)")
    app = build_app(run_dir, roots=args.roots)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {run_dir} at {url}")
    if not args.no_browser:
        threading.Timer(0.7, webbrowser.open, [url]).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
