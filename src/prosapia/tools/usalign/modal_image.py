"""Modal image for usalign (used by ``--executor modal``).

USalign is a single C++ source file, compiled from source onto ``PATH``. It runs
single-threaded on CPU, so the task gets no GPU (the manifest builder sets
``gpus_per_task = 0``).
"""

import modal

RESOURCES = {"cpu": 1, "memory": "4G", "timeout": "00:30:00"}


def image() -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("git", "g++")
        .run_commands(
            "git clone --depth 1 https://github.com/pylelab/USalign /opt/USalign",
            "g++ -O3 -ffast-math -o /usr/local/bin/USalign /opt/USalign/USalign.cpp -lm",
        )
    )
