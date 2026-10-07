"""Modal executor: one container per manifest line, fanned out with ``spawn_map``.

Each task runs the tool's unchanged ``<tool>.sh`` inside the tool's Modal image,
exactly as a SLURM array task would, with ``SAPIA_TASK_ID`` selecting its manifest
line and ``SAPIA_SCHEDULER=modal`` making the prelude skip site activation.

The tool's image comes from an optional ``modal_image.py`` next to its task script:

    def image() -> modal.Image: ...            # required
    RESOURCES = {"gpu": "A100", "cpu": 8, "memory": "32G", "timeout": "02:00:00"}  # optional
    def volumes() -> dict[str, modal.Volume]: ...   # optional extra mounts (weights, DBs)

Run storage is one Modal Volume (``SAPIA_MODAL_RUNS_VOLUME``) mounted at ``/runs``.
``sapia`` itself runs where that Volume is mounted at the same path (the
``sapia modal-shell`` workstation), so paths inside manifests and tables stay valid
in the containers and nothing is stored locally. Tasks run with the mount as cwd and
get the run's ``.env`` (``$SAPIA_DOTENV``, else ``./.env``).

Submission is detached: ``sapia run`` returns once the tasks are queued, like sbatch.
Each task writes ``<log>_<id>.exit`` (its exit code) next to its logs, and the run
records its Modal app in ``<log_dir>/<script>_modal.json``: a task with no ``.exit``
is still running, or was killed (timeout/OOM) if the app has stopped.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

from . import PRELUDE_PATH, SubmitCtx, volume_path, write_manifest
import prosapia.core.executors as executors

RUNS_VOLUME_ENV = "SAPIA_MODAL_RUNS_VOLUME"
DOTENV_ENV = "SAPIA_DOTENV"
MODAL_IMAGE_FILENAME = "modal_image.py"

TASK_MODULE_PATH = Path(__file__).with_name("sapia_modal_task.py")


def get_named_volume(env_var: str, default: str):
    """A persisted Modal Volume named by ``$env_var`` (else ``default``), for tool
    weights, databases and caches that live outside the image."""
    import modal

    return modal.Volume.from_name(
        os.environ.get(env_var) or default, create_if_missing=True
    )


def get_runs_volume():
    """The runs Volume, created as a v2 Volume so hundreds of task containers can
    commit to it concurrently (v1 tolerates only a handful)."""
    import modal

    return modal.Volume.from_name(
        require_env(RUNS_VOLUME_ENV), create_if_missing=True, version=2
    )


def get_dotenv_vars() -> dict[str, str | None]:
    """The run's ``.env`` as a dict: ``$SAPIA_DOTENV`` if set, else ``./.env``."""
    from dotenv import dotenv_values

    path = Path(os.environ.get(DOTENV_ENV) or ".env")
    if not path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def publish_files(runs, local_paths: "Sequence[Path]") -> None:
    """Make submit-time files visible to task containers before any of them starts.

    Writing it through the ``/runs`` mount is not enough. A task container has its
    own mount, and every mount is created with ``allow_background_commits=True``, so
    a mount write reaches the volume backend on a background schedule that
    ``spawn_map`` can outrun. The task then reads a truncated manifest, or no file at
    all -- ``sed: can't read <...>_manifest.txt``, and the task exits 0 having
    written nothing.

    ``runs.commit()`` would force the push, but ``sapia modal-shell`` runs the
    workstation as a Modal *Sandbox* (``modal shell <file>::workstation``), and the
    server rejects VolumeCommit from one. ``batch_upload`` writes server-side through
    the Volume API, so it needs no mount at all and is valid from the Sandbox, from a
    task container and from a laptop alike. ``force=True`` so a rerun under the same
    label overwrites rather than raising.

    The mount writes are kept as well: those are the copies this container reads back
    (e.g. at collect), while these are the copies tasks read.

    This applies to every file written at submit time that a task then reads: the
    manifest itself, and whatever side files a ``build_manifest_fn`` wrote beside it
    (sub-manifests, shard inputs, staged structures) and passed to ``ctx.publish``.
    """
    with runs.batch_upload(force=True) as batch:
        for local_path in local_paths:
            remote = "/" + str(
                volume_path(local_path).relative_to(executors.RUNS_MOUNT)
            )
            batch.put_file(str(local_path), remote)


def publish(paths: "Sequence[Path]") -> None:
    """``PublishFn`` for this executor, handed to a tool as ``ctx.publish``.

    Opens the runs Volume itself, because a manifest is built before any executor is
    entered. See ``publish_files`` for why a mount write is not enough.
    """
    if not paths:
        return
    publish_files(get_runs_volume(), list(paths))


def submit(ctx: SubmitCtx) -> None:
    try:
        import modal
    except ImportError as e:
        raise RuntimeError(
            "The modal executor needs the `modal` package: install prosapia[modal]."
        ) from e

    spec = _load_modal_image(ctx.script.resolve().parent)
    runs_mount = Path(executors.RUNS_MOUNT)
    run_dir = volume_path(ctx.args.run_dir)
    if not run_dir.is_relative_to(runs_mount):
        raise ValueError(
            f"run_dir {run_dir} is not under the runs mount {runs_mount}; the "
            f"modal executor can only run on run_dirs stored on the runs volume."
        )

    write_manifest(ctx.manifest_base, ctx.rows)
    n_tasks = len(ctx.rows)

    runs = get_runs_volume()
    # Publish the manifest before any task can read it. Not runs.commit(): the
    # workstation is a Modal Sandbox, which the server refuses to commit from.
    publish_files(runs, [ctx.manifest_base])
    volumes = {str(runs_mount): runs, **_extra_volumes(spec)}
    resources = resolve_resources(ctx, getattr(spec, "RESOURCES", {}))

    # The task script, its siblings (workers) and the prelude are shipped into the
    # image at the same absolute paths they have here, so SAPIA_PRELUDE and
    # SAPIA_TOOL_DIR resolve identically inside the container.
    tool_dir = ctx.script.resolve().parent
    image = (
        spec.image()
        .add_local_file(PRELUDE_PATH, remote_path=str(PRELUDE_PATH))
        .add_local_dir(tool_dir, remote_path=str(tool_dir))
    )

    app = modal.App(f"sapia-{ctx.tool_name}")
    fn = app.function(
        image=image,
        volumes=volumes,
        secrets=[modal.Secret.from_dict(get_dotenv_vars())],
        max_containers=ctx.args.max_concurrent,
        **resources,
    )(_load_task_module().run_task)
    task_kwargs = {
        "script": str(ctx.script.resolve()),
        "manifest": str(volume_path(ctx.manifest_base)),
        "out_dir": str(volume_path(ctx.out_dir)),
        "log_prefix": str(volume_path(ctx.log_dir) / ctx.script.stem),
        "cwd": str(runs_mount),
        "env": ctx.task_env("modal"),
        "runs_volume": require_env(RUNS_VOLUME_ENV),
    }

    print(
        f"Submitting {n_tasks} task(s) to Modal app {app.name!r} "
        f"({', '.join(f'{k}={v}' for k, v in resources.items()) or 'default resources'})"
    )
    with app.run(detach=True):
        (volume_path(ctx.log_dir) / f"{ctx.script.stem}_modal.json").write_text(
            json.dumps({"app_id": app.app_id, "n_tasks": n_tasks}) + "\n"
        )
        fn.spawn_map(range(1, n_tasks + 1), kwargs=task_kwargs)


def resolve_resources(ctx: SubmitCtx, defaults: dict) -> dict:
    """Merge the tool's ``RESOURCES`` defaults with the run's CLI overrides into
    ``app.function`` kwargs (gpu, cpu, memory in MiB, timeout in seconds)."""
    args = ctx.args
    gpu_type = args.modal_gpu or defaults.get("gpu")
    cpu = args.cpus_per_task or defaults.get("cpu")
    memory = args.mem or defaults.get("memory")
    timeout = args.time or defaults.get("timeout")

    resources: dict = {}
    if args.gpus_per_task > 0:
        if not gpu_type:
            raise ValueError(
                "--gpus-per-task > 0 but no GPU type: pass --modal-gpu or set "
                "RESOURCES['gpu'] in the tool's modal_image.py."
            )
        resources["gpu"] = (
            gpu_type if args.gpus_per_task == 1 else f"{gpu_type}:{args.gpus_per_task}"
        )
    if cpu:
        resources["cpu"] = float(cpu)
    if memory:
        resources["memory"] = parse_mem_mib(memory)
    if timeout:
        resources["timeout"] = parse_time_seconds(timeout)
    return resources


def parse_mem_mib(mem: str | int) -> int:
    """SLURM-style memory (``'32G'``, ``'512M'``, ``'1T'``, bare = MiB) -> MiB."""
    if isinstance(mem, int):
        return mem
    m = re.fullmatch(r"\s*(\d+)\s*([KMGT]?)B?\s*", mem.upper())
    if not m:
        raise ValueError(f"Unrecognized memory value {mem!r} (e.g. '32G', '512M').")
    value, unit = int(m.group(1)), m.group(2) or "M"
    factor = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}[unit]
    return max(1, int(value * factor))


def parse_time_seconds(time: str | int) -> int:
    """SLURM-style wall time -> seconds. Accepts ``MM``, ``MM:SS``, ``HH:MM:SS``,
    ``D-HH``, ``D-HH:MM`` and ``D-HH:MM:SS``."""
    if isinstance(time, int):
        return time
    days = 0
    rest = time.strip()
    if "-" in rest:
        d, rest = rest.split("-", 1)
        days = int(d)
        parts = [int(p) for p in rest.split(":")]
        h, m, s = (parts + [0, 0])[:3]
    else:
        parts = [int(p) for p in rest.split(":")]
        if len(parts) == 1:
            h, m, s = 0, parts[0], 0
        elif len(parts) == 2:
            h, m, s = 0, parts[0], parts[1]
        else:
            h, m, s = parts
    return ((days * 24 + h) * 60 + m) * 60 + s


def _load_modal_image(tool_dir: Path) -> ModuleType:
    path = tool_dir / MODAL_IMAGE_FILENAME
    if not path.is_file():
        raise FileNotFoundError(
            f"No {MODAL_IMAGE_FILENAME} in {tool_dir}; this tool has no Modal image yet."
        )
    spec = importlib.util.spec_from_file_location(
        f"_sapia_modal_image_{tool_dir.name}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "image"):
        raise AttributeError(f"{path} does not define an 'image' function")
    return module


def _load_task_module() -> ModuleType:
    """``sapia_modal_task`` as a standalone top-level module, not part of prosapia,
    so Modal mounts just that file into the image and imports ``run_task`` from it."""
    name = TASK_MODULE_PATH.stem
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, TASK_MODULE_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from {TASK_MODULE_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _extra_volumes(spec: ModuleType) -> dict:
    return spec.volumes() if hasattr(spec, "volumes") else {}


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"The modal executor needs {name} set (in your .env).")
    return value
