import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from .tool import Tool


def _load(spec_py: Path) -> Tool:
    """Load a tool's ``spec.py`` as a submodule of a synthetic package rooted at
    the tool folder, so ``spec.py`` can use relative imports (``from .run import
    ...``) without polluting ``sys.path`` or colliding with other tools' modules.
    """
    tool_dir = spec_py.parent
    pkg_name = f"_sapia_tool_{tool_dir.name}"

    # Register the tool folder as a package whose ``__path__`` is the folder, so
    # its files resolve as namespaced submodules (``<pkg>.run``, ``<pkg>.collect``).
    if pkg_name not in sys.modules:
        pkg_spec = importlib.machinery.ModuleSpec(pkg_name, None, is_package=True)
        pkg_spec.submodule_search_locations = [str(tool_dir)]
        sys.modules[pkg_name] = importlib.util.module_from_spec(pkg_spec)

    mod_spec = importlib.util.spec_from_file_location(f"{pkg_name}.spec", spec_py)
    if mod_spec is None or mod_spec.loader is None:
        raise ImportError(f"Could not load module from {spec_py}")
    mod = importlib.util.module_from_spec(mod_spec)
    sys.modules[mod_spec.name] = mod  # let relative imports resolve the parent
    mod_spec.loader.exec_module(mod)
    return mod.TOOL


def discover(*tools_dirs: Path) -> dict[str, Tool]:
    """Load every tool found across ``tools_dirs``, keyed by ``Tool.name``.

    Dirs are scanned in order and merged, so a tool in a *later* dir overrides a
    same-named tool from an earlier one (user tools shadow built-ins).
    """
    tools: dict[str, Tool] = {}
    for d in tools_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*/spec.py")):
            if t := _load(f):
                tools[t.name] = t
    return tools
