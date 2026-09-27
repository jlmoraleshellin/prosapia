"""Executors + task prelude: SLURM argv and the prelude contract."""

import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from prosapia.core.executors import PRELUDE_PATH, SubmitCtx, get_executor
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


# ── Bundled tools ─────────────────────────────────────────────────────────────


def test_bundled_tools_use_portable_task_scripts():
    for name, tool in discover(BUILTIN_TOOLS_DIR).items():
        script = Path(tool.default_script)
        assert script.suffix == ".sh" and script.is_file(), name
        text = script.read_text()
        assert "SLURM_ARRAY_TASK_ID" not in text, name
        assert "sapia_activate SAPIA_ACTIVATE_" in text, name
