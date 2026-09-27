"""Executors + task prelude: SLURM argv, prelude contract, and Modal fan-out (stubbed)."""

import base64
import shlex
import subprocess
import sys
import types
import json
import shutil
from argparse import Namespace
from pathlib import Path

import pytest

import prosapia.core.executors as executors
from prosapia.core.executors import PRELUDE_PATH, SubmitCtx, get_executor, volume_path
from prosapia.core.executors import modal as modal_exec
from prosapia.core.executors import slurm
from prosapia.core.tool_registry import BUILTIN_TOOLS_DIR, discover


def _args(tmp_path: Path, **overrides) -> Namespace:
    base = dict(
        run_dir=tmp_path,
        script=tmp_path / "tool" / "mytool.sh",
        partitions=None,
        account=None,
        max_concurrent=40,
        max_gpu_fraction=0.5,
        gpus_per_task=1,
        cpus_per_task=None,
        time=None,
        mem=None,
        modal_gpu=None,
    )
    base.update(overrides)
    return Namespace(**base)


def _ctx(tmp_path: Path, rows, **overrides) -> SubmitCtx:
    (tmp_path / "tool").mkdir(exist_ok=True)
    (tmp_path / "out" / "logs").mkdir(parents=True, exist_ok=True)
    return SubmitCtx(
        args=_args(tmp_path, **overrides),
        tool_name="mytool",
        rows=rows,
        manifest_base=tmp_path / "mytool_manifest.txt",
        out_dir=tmp_path / "out",
        log_dir=tmp_path / "out" / "logs",
    )


@pytest.fixture
def sbatch_calls(monkeypatch):
    calls = []

    def fake_run(cmd, env=None, **_):
        calls.append((cmd, env))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(slurm.subprocess, "run", fake_run)
    return calls


# ── SLURM ─────────────────────────────────────────────────────────────────────


def test_get_executor_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown executor"):
        get_executor("pbs")


def test_slurm_argv_matches_pre_refactor(tmp_path, sbatch_calls):
    ctx = _ctx(
        tmp_path,
        [("a", "x"), ("b", "y")],
        account="acc",
        cpus_per_task=4,
        time="01:00:00",
        mem="8G",
    )
    get_executor("slurm")(ctx)

    [(cmd, env)] = sbatch_calls
    assert cmd == [
        "sbatch",
        "--account=acc",
        "--array=1-2%40",
        "--gres=gpu:1",
        "--cpus-per-task=4",
        "--time=01:00:00",
        "--mem=8G",
        f"--output={ctx.log_dir}/mytool_%A_%a.out",
        f"--error={ctx.log_dir}/mytool_%A_%a.err",
        str(ctx.script),
        str(ctx.manifest_base),
        str(ctx.out_dir),
    ]
    assert env["SAPIA_PRELUDE"] == str(PRELUDE_PATH)
    assert env["SAPIA_TOOL_DIR"] == str(ctx.script.resolve().parent)
    assert env["SAPIA_TOOL"] == "mytool"
    assert env["SAPIA_SCHEDULER"] == "slurm"
    assert ctx.manifest_base.read_text() == "a\tx\nb\ty\n"


def test_slurm_cpu_only_drops_gres(tmp_path, sbatch_calls):
    get_executor("slurm")(_ctx(tmp_path, [("a",)], gpus_per_task=0))
    [(cmd, _)] = sbatch_calls
    assert not any(c.startswith("--gres") for c in cmd)


def test_slurm_chunks_over_max_array_size(tmp_path, sbatch_calls, monkeypatch):
    monkeypatch.setattr(slurm, "SLURM_MAX_ARRAY_SIZE", 2)
    ctx = _ctx(tmp_path, [(str(i),) for i in range(5)])
    get_executor("slurm")(ctx)

    arrays = [next(c for c in cmd if c.startswith("--array")) for cmd, _ in sbatch_calls]
    assert arrays == ["--array=1-2%40", "--array=1-2%40", "--array=1-1%40"]
    manifests = [Path(cmd[-2]) for cmd, _ in sbatch_calls]
    assert [m.name for m in manifests] == [
        "mytool_manifest_0.txt",
        "mytool_manifest_1.txt",
        "mytool_manifest_2.txt",
    ]
    assert manifests[2].read_text() == "4\n"


def test_slurm_multi_partition_caps(tmp_path, sbatch_calls):
    ctx = _ctx(tmp_path, [(str(i),) for i in range(5)], partitions="a:4,b:8")
    get_executor("slurm")(ctx)

    got = [
        (
            next(c for c in cmd if c.startswith("--partition=")),
            next(c for c in cmd if c.startswith("--array")),
        )
        for cmd, _ in sbatch_calls
    ]
    assert got == [("--partition=a", "--array=1-3%2"), ("--partition=b", "--array=1-2%4")]


# ── Prelude ───────────────────────────────────────────────────────────────────


def _run_prelude(tmp_path: Path, body: str, env: dict) -> subprocess.CompletedProcess:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("first\tA\nsecond\tB\n")
    script = tmp_path / "task.sh"
    script.write_text(f'set -euo pipefail\nsource "$SAPIA_PRELUDE"\n{body}\n')
    return subprocess.run(
        ["bash", str(script), str(manifest), str(tmp_path / "out")],
        env={"PATH": "/usr/bin:/bin", "SAPIA_PRELUDE": str(PRELUDE_PATH), **env},
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_prelude_modal_selects_line_and_skips_activation(tmp_path):
    r = _run_prelude(
        tmp_path,
        'sapia_activate SAPIA_ACTIVATE_MYTOOL\necho "$SAPIA_TASK_ID|$SAPIA_LINE|${ACTIVATED:-no}"',
        {"SAPIA_TASK_ID": "2", "SAPIA_SCHEDULER": "modal"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2|second\tB|no"


def test_prelude_slurm_falls_back_to_array_id_and_activates(tmp_path):
    act = tmp_path / "act.sh"
    act.write_text("ACTIVATED=yes\necho $UNSET_IN_ACTIVATION >/dev/null\n")
    r = _run_prelude(
        tmp_path,
        'sapia_activate SAPIA_ACTIVATE_MYTOOL\necho "$SAPIA_SCHEDULER|$SAPIA_LINE|$ACTIVATED"',
        {"SLURM_ARRAY_TASK_ID": "1", "SAPIA_ACTIVATE_MYTOOL": str(act)},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "slurm|first\tA|yes"


def test_prelude_fails_when_activation_unset(tmp_path):
    r = _run_prelude(
        tmp_path,
        "sapia_activate SAPIA_ACTIVATE_MYTOOL\necho reached",
        {"SLURM_ARRAY_TASK_ID": "1"},
    )
    assert r.returncode != 0
    assert "reached" not in r.stdout
    assert "set SAPIA_ACTIVATE_MYTOOL in your .env" in r.stderr


# ── Modal (stubbed SDK) ───────────────────────────────────────────────────────


class _FakeImage:
    def __init__(self):
        self.local = []

    def add_local_file(self, local, remote_path):
        self.local.append((str(local), remote_path))
        return self

    def add_local_dir(self, local, remote_path):
        self.local.append((str(local), remote_path))
        return self


class _FakeVolume:
    def __init__(self, name):
        self.name = name
        self.commits = 0

    def commit(self):
        self.commits += 1


class _FakeFunction:
    def __init__(self, fn, kwargs):
        self.fn, self.kwargs, self.spawned = fn, kwargs, None

    def spawn_map(self, inputs):
        self.spawned = list(inputs)


class _FakeApp:
    last = None

    def __init__(self, name):
        self.name = name
        self.app_id = "ap-test"
        self.run_kwargs = None
        _FakeApp.last = self

    def function(self, **kwargs):
        def deco(fn):
            self.fn = _FakeFunction(fn, kwargs)
            return self.fn

        return deco

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_modal(monkeypatch):
    volumes = {}

    def from_name(name, **kwargs):
        vol = volumes.setdefault(name, _FakeVolume(name))
        vol.from_name_kwargs = kwargs
        return vol

    mod = types.SimpleNamespace(
        App=_FakeApp,
        Volume=types.SimpleNamespace(from_name=from_name),
        Secret=types.SimpleNamespace(from_dict=lambda d: ("secret", d)),
    )
    monkeypatch.setitem(sys.modules, "modal", mod)
    return volumes


def _modal_tool(tmp_path: Path) -> Path:
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir(exist_ok=True)
    (tool_dir / "modal_image.py").write_text(
        "import sys\n"
        "RESOURCES = {'gpu': 'L4', 'cpu': 2, 'memory': '4G', 'timeout': '00:30:00'}\n"
        "def image():\n"
        "    return sys.modules['_test_fake_image']()\n"
    )
    script = tool_dir / "mytool.sh"
    script.write_text(
        'set -euo pipefail\nsource "$SAPIA_PRELUDE"\n'
        "sapia_activate SAPIA_ACTIVATE_MYTOOL\n"
        'echo "$SAPIA_SCHEDULER $SAPIA_TOOL $SAPIA_TASK_ID $SAPIA_LINE $PWD"\n'
    )
    return script


def test_modal_submit_fans_out_and_runs_script(tmp_path, fake_modal, monkeypatch):
    monkeypatch.setitem(sys.modules, "_test_fake_image", _FakeImage)
    monkeypatch.setenv("SAPIA_MODAL_RUNS_VOLUME", "runs")
    monkeypatch.setattr(executors, "RUNS_MOUNT", str(tmp_path))
    dotenv = tmp_path / "ws.env"
    dotenv.write_text("FOO=bar\n")
    monkeypatch.setenv("SAPIA_DOTENV", str(dotenv))
    # The client's cwd must not leak into the task: tasks run from the mount.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    script = _modal_tool(tmp_path)

    ctx = _ctx(tmp_path, [("a",), ("b",), ("c",)], script=script, max_concurrent=7)
    get_executor("modal")(ctx)

    app = _FakeApp.last
    assert app.name == "sapia-mytool"
    assert app.run_kwargs == {"detach": True}
    assert app.fn.spawned == [1, 2, 3]
    kw = app.fn.kwargs
    assert kw["max_containers"] == 7
    assert kw["serialized"] is True
    assert kw["gpu"] == "L4"
    assert kw["cpu"] == 2.0
    assert kw["memory"] == 4096
    assert kw["timeout"] == 1800
    assert kw["volumes"] == {str(tmp_path): fake_modal["runs"]}
    assert fake_modal["runs"].from_name_kwargs == {"create_if_missing": True, "version": 2}
    assert kw["secrets"] == [("secret", {"FOO": "bar"})]
    assert (str(PRELUDE_PATH), str(PRELUDE_PATH)) in kw["image"].local
    assert ctx.manifest_base.read_text() == "a\nb\nc\n"

    # Run one task's function locally: the unchanged script runs with modal env.
    assert app.fn.fn(2) == 0
    out = (ctx.log_dir / "mytool_2.out").read_text().strip()
    assert out == f"modal mytool 2 b {tmp_path}"
    assert (ctx.log_dir / "mytool_2.exit").read_text() == "0\n"
    assert fake_modal["runs"].commits == 1
    assert json.loads((ctx.log_dir / "mytool_modal.json").read_text()) == {
        "app_id": "ap-test",
        "n_tasks": 3,
    }


def test_modal_task_records_failures(tmp_path, fake_modal, monkeypatch):
    monkeypatch.setitem(sys.modules, "_test_fake_image", _FakeImage)
    monkeypatch.setenv("SAPIA_MODAL_RUNS_VOLUME", "runs")
    monkeypatch.setattr(executors, "RUNS_MOUNT", str(tmp_path))
    script = _modal_tool(tmp_path)
    script.write_text('source "$SAPIA_PRELUDE"\nexit 3\n')
    ctx = _ctx(tmp_path, [("a",)], script=script)
    get_executor("modal")(ctx)
    run_task = _FakeApp.last.fn.fn

    assert run_task(1) == 3
    assert (ctx.log_dir / "mytool_1.exit").read_text() == "3\n"

    # The wrapper itself failing (here: no log dir) still leaves an .exit behind.
    shutil.rmtree(ctx.log_dir)
    ctx.log_dir.mkdir()
    (ctx.log_dir / "mytool_1.out").mkdir()  # can't be opened as a file
    with pytest.raises(IsADirectoryError):
        run_task(1)
    assert (ctx.log_dir / "mytool_1.exit").read_text() == "255\n"
    assert fake_modal["runs"].commits == 2


def test_modal_keeps_symlinked_mount_paths(tmp_path, fake_modal, monkeypatch):
    # In a Modal container the mount is a symlink into /__modal/volumes/<id>.
    monkeypatch.setitem(sys.modules, "_test_fake_image", _FakeImage)
    target = tmp_path / "vo-internal"
    target.mkdir()
    mount = tmp_path / "runs"
    mount.symlink_to(target)
    monkeypatch.setenv("SAPIA_MODAL_RUNS_VOLUME", "runs")
    monkeypatch.setattr(executors, "RUNS_MOUNT", str(mount))
    # The workstation shell starts in the physical dir, not the mount.
    monkeypatch.chdir(target)
    script = _modal_tool(tmp_path)

    (mount / "out" / "logs").mkdir(parents=True)
    ctx = SubmitCtx(
        args=_args(Path("."), script=script),
        tool_name="mytool",
        rows=[("a",)],
        manifest_base=Path("mytool_manifest.txt"),
        out_dir=Path("out"),
        log_dir=Path("out/logs"),
    )
    get_executor("modal")(ctx)

    assert _FakeApp.last.fn.fn(1) == 0
    out = (target / "out" / "logs" / "mytool_1.out").read_text().split()
    # Task sees the out_dir via the mount path, never the symlink target.
    assert out[-1] == str(mount)
    code = _FakeApp.last.fn.fn.__code__
    cells = [c.cell_contents for c in _FakeApp.last.fn.fn.__closure__]
    paths = dict(zip(code.co_freevars, cells))
    for name in ("manifest", "out_dir", "log_prefix"):
        assert paths[name].startswith(str(mount)), (name, paths[name])


def test_modal_rejects_run_dir_outside_mount(tmp_path, fake_modal, monkeypatch):
    monkeypatch.setitem(sys.modules, "_test_fake_image", _FakeImage)
    monkeypatch.setenv("SAPIA_MODAL_RUNS_VOLUME", "runs")
    monkeypatch.setattr(executors, "RUNS_MOUNT", str(tmp_path / "elsewhere"))
    script = _modal_tool(tmp_path)
    with pytest.raises(ValueError, match="not under the runs mount"):
        get_executor("modal")(_ctx(tmp_path, [("a",)], script=script))


def test_volume_path_maps_real_mount_back(tmp_path, monkeypatch):
    target = tmp_path / "vo-internal"
    (target / "run").mkdir(parents=True)
    mount = tmp_path / "runs"
    mount.symlink_to(target)
    monkeypatch.setattr(executors, "RUNS_MOUNT", str(mount))
    assert volume_path(target / "run") == mount / "run"
    assert volume_path(target) == mount
    monkeypatch.chdir(target)
    assert volume_path("run/x.pdb") == mount / "run" / "x.pdb"
    # Outside the mount (and off Modal) it is plain abspath: symlinks are kept.
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "vo-internal-2", target_is_directory=True)
    assert volume_path(link) == link
    assert volume_path(str(tmp_path / "vo-internal-sibling")) == tmp_path / "vo-internal-sibling"


def test_modal_requires_modal_image(tmp_path, fake_modal):
    with pytest.raises(FileNotFoundError, match="modal_image.py"):
        get_executor("modal")(_ctx(tmp_path, [("a",)]))


def test_modal_resources_cli_overrides(tmp_path):
    ctx = _ctx(
        tmp_path, [], gpus_per_task=2, modal_gpu="H100", cpus_per_task=16, mem="1T", time="1-02:00:00"
    )
    assert modal_exec.resolve_resources(ctx, {"gpu": "L4", "cpu": 2}) == {
        "gpu": "H100:2",
        "cpu": 16.0,
        "memory": 1024 * 1024,
        "timeout": 26 * 3600,
    }
    with pytest.raises(ValueError, match="no GPU type"):
        modal_exec.resolve_resources(_ctx(tmp_path, []), {})
    assert modal_exec.resolve_resources(_ctx(tmp_path, [], gpus_per_task=0), {}) == {}


@pytest.mark.parametrize(
    "raw,secs", [("30", 1800), ("10:05", 605), ("02:00:00", 7200), ("2-00", 172800)]
)
def test_parse_time_seconds(raw, secs):
    assert modal_exec.parse_time_seconds(raw) == secs


@pytest.mark.parametrize("raw,mib", [("512M", 512), ("8G", 8192), ("2048", 2048)])
def test_parse_mem_mib(raw, mib):
    assert modal_exec.parse_mem_mib(raw) == mib


def test_modal_dotenv_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("SAPIA_DOTENV", raising=False)
    monkeypatch.chdir(tmp_path)
    assert modal_exec.get_dotenv_vars() == {}
    (tmp_path / ".env").write_text("A=1\nB\n")
    assert modal_exec.get_dotenv_vars() == {"A": "1"}


# ── Modal workstation ─────────────────────────────────────────────────────────


def test_modal_shell_argv():
    from prosapia.cli.modal_shell import WORKSTATION, modal_shell_argv

    assert WORKSTATION.is_file()
    ref = f"{WORKSTATION}::workstation"
    assert modal_shell_argv(Namespace(cmd=None)) == [sys.executable, "-m", "modal", "shell", ref]
    flag, wrapped = modal_shell_argv(Namespace(cmd="sapia --help"))[-2:]
    assert flag == "--cmd"
    assert '"' not in wrapped and "'" not in wrapped


def test_modal_shell_cmd_survives_modals_bash_wrapper(tmp_path):
    from prosapia.cli.modal_shell import modal_shell_argv

    (tmp_path / "a b").mkdir()
    cmd = """for f in *; do echo "got: $f"; done; echo 'single $HOME'; exit 7"""
    wrapped = modal_shell_argv(Namespace(cmd=cmd))[-1]
    assert base64.b64encode(cmd.encode()).decode() in wrapped
    # Exactly what modal/cli/shell.py does with --cmd.
    argv = shlex.split(f'/bin/bash -c "{wrapped}"')
    result = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 7
    assert result.stdout == "got: a b\nsingle $HOME\n"


def test_workstation_spec(tmp_path, monkeypatch):
    pytest.importorskip("modal")
    import importlib.util

    (tmp_path / "tools").mkdir()
    # Set via monkeypatch (restored after), so the module's load_dotenv adds nothing.
    monkeypatch.setenv("SAPIA_MODAL_RUNS_VOLUME", "runs")
    monkeypatch.setenv("PROSAPIA_TOOLS_DIR", "tools")
    monkeypatch.chdir(tmp_path)
    from prosapia.cli.modal_shell import WORKSTATION

    spec = importlib.util.spec_from_file_location("_sapia_workstation", WORKSTATION)
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)

    assert ws.RUNS_MOUNT == "/runs"
    deps = ws._dependencies()
    assert any(d.startswith("pandas") for d in deps)
    assert any(d.startswith("modal==") for d in deps)
    assert not any("extra ==" in d for d in deps)


# ── Bundled tools ─────────────────────────────────────────────────────────────


def test_bundled_tools_use_portable_task_scripts():
    for name, tool in discover(BUILTIN_TOOLS_DIR).items():
        script = Path(tool.default_script)
        assert script.suffix == ".sh" and script.is_file(), name
        text = script.read_text()
        assert "SLURM_ARRAY_TASK_ID" not in text, name
        assert "sapia_activate SAPIA_ACTIVATE_" in text, name
