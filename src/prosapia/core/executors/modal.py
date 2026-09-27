"""Modal executor: one container per manifest line, fanned out with ``spawn_map``.

Each task runs the tool's unchanged ``<tool>.sh`` inside the tool's Modal image,
exactly as a SLURM array task would, with ``SAPIA_TASK_ID`` selecting its manifest
line and ``SAPIA_SCHEDULER=modal`` making the prelude skip site activation.

The tool's image comes from an optional ``modal_image.py`` next to its task script:

    def image() -> modal.Image: ...            # required
    RESOURCES = {"gpu": "A100", "cpu": 8, "memory": "32G", "timeout": "02:00:00"}  # optional
    def volumes() -> dict[str, modal.Volume]: ...   # optional extra mounts (weights, DBs)

Run storage is one Modal Volume (``SAPIA_MODAL_RUNS_VOLUME``) mounted at
``SAPIA_MODAL_RUNS_MOUNT``, the same absolute path the run_dir lives under where
``sapia`` runs, so paths inside manifests and tables stay valid in the containers.
Submission is detached: ``sapia run`` returns once the tasks are queued, like sbatch.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType

from . import PRELUDE_PATH, SubmitCtx, write_manifest

RUNS_VOLUME_ENV = "SAPIA_MODAL_RUNS_VOLUME"
RUNS_MOUNT_ENV = "SAPIA_MODAL_RUNS_MOUNT"
MODAL_IMAGE_FILENAME = "modal_image.py"

# The task function is pickled by value on the client, so tool images must run the
# same Python minor version as the process calling `sapia run`.
PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"


def named_volume(env_var: str, default: str):
    """A persisted Modal Volume named by ``$env_var`` (else ``default``), for tool
    weights, databases and caches that live outside the image."""
    import modal

    return modal.Volume.from_name(
        os.environ.get(env_var) or default, create_if_missing=True
    )


def submit(ctx: SubmitCtx) -> None:
    try:
        import modal
    except ImportError as e:
        raise RuntimeError(
            "The modal executor needs the `modal` package: install prosapia[modal]."
        ) from e

    spec = _load_modal_image(ctx.script.resolve().parent)
    runs_volume_name = _require_env(RUNS_VOLUME_ENV)
    runs_mount = Path(_require_env(RUNS_MOUNT_ENV))
    run_dir = Path(ctx.args.run_dir).resolve()
    if not run_dir.is_relative_to(runs_mount):
        raise ValueError(
            f"run_dir {run_dir} is not under {RUNS_MOUNT_ENV}={runs_mount}; the "
            f"modal executor can only run on run_dirs stored on the runs volume."
        )

    write_manifest(ctx.manifest_base, ctx.rows)
    n_tasks = len(ctx.rows)

    runs_volume = modal.Volume.from_name(runs_volume_name)
    volumes = {str(runs_mount): runs_volume, **_extra_volumes(spec)}
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

    env = ctx.task_env("modal")
    script = str(ctx.script.resolve())
    manifest = str(ctx.manifest_base.resolve())
    out_dir = str(ctx.out_dir.resolve())
    log_prefix = str(ctx.log_dir.resolve() / ctx.script.stem)
    cwd = str(Path.cwd())

    # Pickled by value (serialized=True): keep its imports local so the container
    # only needs the stdlib, not prosapia.
    def run_task(task_id: int) -> int:
        import os
        import subprocess
        from pathlib import Path

        Path(cwd).mkdir(parents=True, exist_ok=True)
        with (
            open(f"{log_prefix}_{task_id}.out", "w") as out,
            open(f"{log_prefix}_{task_id}.err", "w") as err,
        ):
            code = subprocess.run(
                ["bash", script, manifest, out_dir],
                env={**os.environ, **env, "SAPIA_TASK_ID": str(task_id)},
                stdout=out,
                stderr=err,
                cwd=cwd,
            ).returncode
        runs_volume.commit()
        return code

    app = modal.App(f"sapia-{ctx.tool_name}")
    fn = app.function(
        image=image,
        volumes=volumes,
        max_containers=ctx.args.max_concurrent,
        serialized=True,
        **resources,
    )(run_task)

    print(
        f"Submitting {n_tasks} task(s) to Modal app {app.name!r} "
        f"({', '.join(f'{k}={v}' for k, v in resources.items()) or 'default resources'})"
    )
    with app.run(detach=True):
        fn.spawn_map(range(1, n_tasks + 1))


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


def _extra_volumes(spec: ModuleType) -> dict:
    return spec.volumes() if hasattr(spec, "volumes") else {}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"The modal executor needs {name} set (in your .env).")
    return value
