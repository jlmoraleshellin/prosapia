"""``sapia init --config`` -- scaffold the starter config files into a directory.

prosapia bundles two kinds of starter template (under ``src/prosapia/templates/``):
a ``.env`` seed and one activation-script template per tool. Because prosapia is
installed into the user's own venv -- not run from a repo checkout -- these are
shipped inside the package and copied out on demand rather than ``cp``-t from the
source tree. ``scaffold_config`` writes them into a destination dir (default cwd):

    <dest>/.env                     # from templates/env.example
    <dest>/activation/<tool>.sh     # from templates/activation/*.sh

Existing files are left untouched unless ``force`` is set. See docs/configuration.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Bundled templates live at src/prosapia/templates/ (this module is in cli/).
# Same Path(__file__).parent idiom as core.base_sbatch.PRELUDE_PATH / BUILTIN_TOOLS_DIR.
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
ENV_TEMPLATE = TEMPLATES_DIR / "env.example"
ACTIVATION_DIR = TEMPLATES_DIR / "activation"


def _copy(src: Path, dst: Path, force: bool) -> bool:
    """Copy ``src`` to ``dst`` unless it exists (and ``force`` is off). True if written."""
    if dst.exists() and not force:
        print(f"  skip   {dst} (exists; --force to overwrite)")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"  wrote  {dst}")
    return True


def scaffold_config(dest: Path, force: bool = False) -> None:
    """Write the bundled ``.env`` seed and activation templates into ``dest``.

    ``.env`` lands at ``dest/.env``; each activation template lands under
    ``dest/activation/``. Existing files are skipped unless ``force``.
    """
    dest = dest.expanduser()
    print(f"Scaffolding prosapia config into {dest.resolve()}")

    _copy(ENV_TEMPLATE, dest / ".env", force)
    for template in sorted(ACTIVATION_DIR.glob("*.sh")):
        _copy(template, dest / "activation" / template.name, force)

    print(
        "\nNext:\n"
        "  1. Edit .env for your site (global settings + SAPIA_ACTIVATE_<NAME> pointers).\n"
        "  2. Edit the activation/ script for each tool you run, then point its\n"
        "     SAPIA_ACTIVATE_<NAME> in .env at that script.\n"
        "  See docs/configuration.md for the full reference."
    )
