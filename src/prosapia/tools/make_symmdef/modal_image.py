"""Modal image for make_symmdef (used by ``--executor modal``).

``make_symmdef.sh`` runs ``$ROSETTA/src/apps/public/symmetry/make_symmdef_file.pl``
and nothing else from Rosetta. That script is standalone Perl (core modules only),
so the image does not build Rosetta: it fetches the one file from the public
RosettaCommons/rosetta repository at ``ROSETTA_REF`` into a tree laid out like
``rosetta/source``, and points ``ROSETTA`` at it. Single-threaded on CPU, so the
task gets no GPU (the manifest builder sets ``gpus_per_task = 0``).

Rosetta is free for academic and non-commercial use; commercial use needs a
license from RosettaCommons.

Under modal the prelude skips site activation, so this image supplies ``ROSETTA``
itself. It belongs in the activation script, not in ``.env``: the run's ``.env``
reaches the container and would override it with a path that only exists on your
cluster.
"""

import modal

ROSETTA_REF = "main"
ROSETTA_DIR = "/opt/rosetta"
MAKESYMM_REL = "src/apps/public/symmetry/make_symmdef_file.pl"
RESOURCES = {"cpu": 1, "memory": "4G", "timeout": "00:30:00"}


def image() -> modal.Image:
    url = (
        "https://raw.githubusercontent.com/RosettaCommons/rosetta/"
        f"{ROSETTA_REF}/source/{MAKESYMM_REL}"
    )
    return (
        modal.Image.debian_slim(python_version="3.12")
        # Full perl: debian_slim ships perl-base, which lacks Math::Trig.
        .apt_install("perl", "curl")
        .run_commands(
            f"mkdir -p {ROSETTA_DIR}/{MAKESYMM_REL.rsplit('/', 1)[0]}",
            f"curl -fsSL {url} -o {ROSETTA_DIR}/{MAKESYMM_REL}",
            f"perl -c {ROSETTA_DIR}/{MAKESYMM_REL}",
        )
        .env({"ROSETTA": ROSETTA_DIR})
    )
