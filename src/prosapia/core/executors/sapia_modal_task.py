"""The Modal task entrypoint: runs one manifest line's ``<tool>.sh``.

Modal ships this file into every tool image as a standalone module and imports
``run_task`` from it, so nothing is pickled and the image may run any Python Modal
supports. Keep it free of prosapia imports: the container only has the stdlib and
the modal client.
"""

import os
import subprocess


def run_task(
    task_id: int,
    *,
    script: str,
    manifest: str,
    out_dir: str,
    log_prefix: str,
    cwd: str,
    env: dict,
    runs_volume: str,
) -> int:
    import modal

    # 255 unless the script ran: the .exit file is written whatever happens.
    code = 255
    try:
        with open(f"{log_prefix}_{task_id}.out", "w") as out, open(
            f"{log_prefix}_{task_id}.err", "w"
        ) as err:
            code = subprocess.run(
                ["bash", script, manifest, out_dir],
                env={**os.environ, **env, "SAPIA_TASK_ID": str(task_id), "PWD": cwd},
                stdout=out,
                stderr=err,
                cwd=cwd,
            ).returncode
    finally:
        with open(f"{log_prefix}_{task_id}.exit", "w") as f:
            f.write(f"{code}\n")
        modal.Volume.from_name(runs_volume, version=2).commit()
    return code
