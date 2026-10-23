"""Tests for ``sapia serve``: the tree, table and file API over a synthetic run_dir."""

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prosapia.cli.merge import MergeArgs, merge_from_args  # noqa: E402
from prosapia.cli.serve import build_serve_parser  # noqa: E402
from prosapia.core import GEN, PARENT_NAME, PARENT_TABLE, DataManager, Table  # noqa: E402
from prosapia.core.naming import RUN_META_FILENAME, SUBMISSIONS_DIRNAME  # noqa: E402
from prosapia.server.app import build_app  # noqa: E402

PDB = "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\nEND\n"


def _write(dm: DataManager, table: Table, rows: dict[str, dict]) -> None:
    dm.rm.register_table(table)
    df = dm.read_frame(table.table_name)
    for name, data in rows.items():
        df = dm.update(df, name, data)
    dm.write_frame(table.table_name, df)


def _child(parent_name: str, parent_table: str, gen: int, **extra) -> dict:
    return {PARENT_NAME: parent_name, PARENT_TABLE: parent_table, GEN: gen, **extra}


def _meta(leaf_dir: Path, **fields) -> None:
    leaf_dir.mkdir(parents=True, exist_ok=True)
    (leaf_dir / RUN_META_FILENAME).write_text(json.dumps(fields))


def _logs(leaf_dir: Path, script: str, exits: list[int | None]) -> None:
    log_dir = leaf_dir / f"{script}_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for i, code in enumerate(exits, start=1):
        (log_dir / f"{script}_{i}.out").write_text(f"task {i}\n")
        (log_dir / f"{script}_{i}.err").write_text("")
        if code is not None:
            (log_dir / f"{script}_{i}.exit").write_text(f"{code}\n")


def build_run_dir(base: Path, run: str = "run") -> Path:
    """``<base>/outputs/<run>``: a root, two children, an update leaf, a reserved
    table, a merge, a junk dir and an orphan table. Paths are stored
    ``outputs/<run>/...``, as ``sapia`` run from ``base`` would store them."""
    rd = base / "outputs" / run
    rd.mkdir(parents=True)
    dm = DataManager(rd)

    rfd = rd / "table0" / "rfdiffusion"
    _meta(rfd, tool="rfdiffusion", dir_label="", input_column="", timestamp="t0")
    _logs(rfd, "rfdiffusion", [0, 1, None])
    sub = rfd / SUBMISSIONS_DIRNAME / "00"
    sub.mkdir(parents=True)
    (sub / "D0.pdb").write_text(PDB)
    _write(
        dm,
        Table("table0", 0, "", None, "rfdiffusion"),
        {
            "D0": {"rfdiffusion_status": "OK", "rfdiffusion_path": f"outputs/{run}/table0/rfdiffusion/.submissions/00/D0.pdb", "score": 1.5},
            "D1": {"rfdiffusion_status": "OK", "rfdiffusion_path": f"outputs/{run}/table0/rfdiffusion/.submissions/00/D1.pdb", "score": float("nan")},
        },
    )
    (rd / "table0" / "notes").mkdir()
    (rd / "table0" / "notes" / "todo.txt").write_text("junk\n")

    _meta(rd / "table1_a" / "proteinmpnn", tool="proteinmpnn", dir_label="")
    _meta(rd / "table1_a" / "alphafold3", tool="alphafold3", dir_label="")
    _write(
        dm,
        Table("table1_a", 1, "a", "table0", "proteinmpnn"),
        {
            "D0_f0": _child("D0", "table0", 1, proteinmpnn_sequence="AAA", proteinmpnn_score=0.1, alphafold3_status="OK", alphafold3_ptm=0.8),
            "D1_f0": _child("D1", "table0", 1, proteinmpnn_sequence="CCC", proteinmpnn_score=0.2, alphafold3_status="error: x", alphafold3_ptm=float("nan")),
        },
    )
    _write(
        dm,
        Table("table1_b", 1, "b", "table0", "proteinmpnn"),
        {"D0_f0": _child("D0", "table0", 1, proteinmpnn_sequence="GGG", proteinmpnn_score=0.3)},
    )
    dm.rm.register_table(Table("table2_x", 2, "a_x", "table1_a", "boltz"))
    _meta(rd / "table2_x" / "boltz", tool="boltz", dir_label="")
    _meta(rd / "table1_a" / "pyrosetta", tool="pyrosetta", dir_label="")
    _logs(rd / "table1_a" / "pyrosetta", "pyrosetta", [0, 0])

    merge_from_args(MergeArgs(run_dir=rd, tables=["table1_a", "table1_b"], table_label="merged", lift=False))
    (rd / "seed.tsv").write_text("name\tsequence\nS0\tMKV\n")
    return rd


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return build_run_dir(tmp_path)


@pytest.fixture
def client(run_dir):
    return TestClient(build_app(run_dir))


def _node(tree: dict, name: str) -> dict:
    return next(t for t in tree["tables"] if t["name"] == name)


def test_tree_tables_and_edges(client):
    tree = client.get("/api/tree").json()
    names = [t["name"] for t in tree["tables"]]
    assert names == ["table0", "table1_a", "table1_b", "table1_merged", "table2_x", "seed"]

    root = _node(tree, "table0")
    assert root["gen"] == 0 and root["parent"] is None and root["collected"]
    assert root["n_rows"] == 2 and root["tool"] == "rfdiffusion"
    assert [leaf["name"] for leaf in root["leaves"]] == ["rfdiffusion"]  # notes/ is junk
    rfd = root["leaves"][0]
    assert rfd["kind"] == "create" and rfd["status"] == "collected"
    assert rfd["tasks"] == {"n": 3, "ok": 1, "failed": 1, "pending": 1, "executor": "local"}
    assert rfd["rows"] == {"ok": 2, "other": 0}

    seed = _node(tree, "seed")
    assert seed["registered"] is False and seed["collected"] and seed["gen"] is None

    reserved = _node(tree, "table2_x")
    assert reserved["collected"] is False and reserved["n_rows"] is None
    assert reserved["leaves"][0]["status"] == "reserved"

    edges = {(e["from"], e["to"], e["kind"]) for e in tree["edges"]}
    assert ("table0", "table1_a", "parent") in edges
    assert ("table1_a", "table2_x", "parent") in edges
    assert ("table1_a", "table1_merged", "merge") in edges
    assert ("table1_b", "table1_merged", "merge") in edges
    merged = _node(tree, "table1_merged")
    assert merged["sources"] == ["table1_a", "table1_b"]
    assert merged["leaves"][0]["kind"] == "merge"


def test_tree_update_leaves(client):
    tree = client.get("/api/tree").json()
    leaves = {leaf["name"]: leaf for leaf in _node(tree, "table1_a")["leaves"]}
    assert set(leaves) == {"proteinmpnn", "alphafold3", "pyrosetta"}
    assert leaves["proteinmpnn"]["kind"] == "create"
    af3 = leaves["alphafold3"]
    assert af3["kind"] == "update" and af3["status"] == "collected"
    assert af3["rows"] == {"ok": 1, "other": 1}
    ros = leaves["pyrosetta"]
    assert ros["status"] == "submitted" and ros["tasks"]["ok"] == 2


def test_table_joined_and_raw(client):
    joined = client.get("/api/tables/table1_a").json()
    cols = {c["name"]: c for c in joined["columns"]}
    assert joined["n_rows"] == 2 and "warning" not in joined
    assert cols["score"]["source"] == "table0" and cols["score"]["is_numeric"]
    assert cols["rfdiffusion_path"]["source"] == "table0" and cols["rfdiffusion_path"]["is_path"]
    assert cols["proteinmpnn_sequence"]["source"] == "own" and not cols["proteinmpnn_sequence"]["is_path"]
    assert cols["alphafold3_ptm"] == {"name": "alphafold3_ptm", "source": "own", "is_numeric": True, "n_non_null": 1, "min": 0.8, "max": 0.8}
    data = joined["data"]
    assert data["names"][0] == "name"
    assert data["cols"][data["names"].index("alphafold3_ptm")] == [0.8, None]
    assert data["cols"][data["names"].index("score")] == [1.5, None]

    raw = client.get("/api/tables/table1_a", params={"joined": "false"}).json()
    raw_names = raw["data"]["names"]
    assert "score" not in raw_names and "proteinmpnn_score" in raw_names
    assert client.get("/api/tables/nope").status_code == 404


def test_row_detail(client):
    out = client.get("/api/tables/table1_a/rows/D0_f0").json()
    assert out["row"]["proteinmpnn_sequence"] == "AAA" and out["row"]["score"] == 1.5
    assert [(a["table"], a["name"]) for a in out["lineage"]] == [("table0", "D0")]
    assert out["lineage"][0]["row"]["score"] == 1.5
    assert out["children"] == []
    root_row = client.get("/api/tables/table0/rows/D0").json()
    assert root_row["children"] == [
        {"table": "table1_a", "names": ["D0_f0"]},
        {"table": "table1_b", "names": ["D0_f0"]},
        {"table": "table1_merged", "names": ["D0_f0_a", "D0_f0_b"]},
    ]
    paths = {p["column"]: p for p in out["paths"]}
    assert paths["rfdiffusion_path"]["kind"] == "structure" and paths["rfdiffusion_path"]["exists"]
    assert client.get("/api/tables/table0/rows/D0").json()["lineage"] == []
    assert client.get("/api/tables/table0/rows/nope").status_code == 404
    missing = client.get("/api/tables/table1_a/rows/D1_f0").json()
    assert {p["column"]: p["exists"] for p in missing["paths"]} == {"rfdiffusion_path": False}


def test_leaf_detail(client):
    out = client.get("/api/leaves/table0/rfdiffusion").json()
    assert out["meta"]["tool"] == "rfdiffusion"
    assert [t["exit"] for t in out["tasks"]] == [0, 1, None]
    assert out["tasks"][0]["out"] == "table0/rfdiffusion/rfdiffusion_logs/rfdiffusion_1.out"
    assert [(f["submission"], f["name"]) for f in out["files"] if f["name"] == "D0.pdb"] == [("00", "D0.pdb")]
    log = client.get("/api/file", params={"path": out["tasks"][0]["out"]}).json()
    assert log["text"] == "task 1\n" and not log["truncated"]
    assert client.get("/api/leaves/table0/nope").status_code == 404
    assert client.get("/api/leaves/table0/..").status_code == 404


def test_structure_and_sandbox(run_dir, tmp_path):
    client = TestClient(build_app(run_dir))
    ok = client.get("/api/structure", params={"path": "outputs/run/table0/rfdiffusion/.submissions/00/D0.pdb"})
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("chemical/x-pdb")
    assert ok.text == PDB
    assert client.get("/api/structure", params={"path": "outputs/run/table0/rfdiffusion/D1.pdb"}).status_code == 404

    outside = tmp_path / "elsewhere" / "x.pdb"
    outside.parent.mkdir()
    outside.write_text(PDB)
    assert client.get("/api/structure", params={"path": str(outside)}).status_code == 403
    assert client.get("/api/structure", params={"path": "../../elsewhere/x.pdb"}).status_code == 403
    assert client.get("/api/file", params={"path": "outputs/run/table0/rfdiffusion/.submissions/00/D0.pdb"}).status_code == 400

    rooted = TestClient(build_app(run_dir, roots=[outside.parent]))
    assert rooted.get("/api/structure", params={"path": str(outside)}).status_code == 200


def test_gz_structure(run_dir):
    import gzip

    gz = run_dir / "table0" / "rfdiffusion" / "D1.pdb.gz"
    with gzip.open(gz, "wt") as f:
        f.write(PDB)
    client = TestClient(build_app(run_dir))
    res = client.get("/api/structure", params={"path": "outputs/run/table0/rfdiffusion/D1.pdb.gz"})
    assert res.status_code == 200 and res.text == PDB


def test_cache_invalidation(run_dir, client):
    before = client.get("/api/tables/table1_a").json()["data"]["names"]
    assert "new_metric" not in before
    dm = DataManager(run_dir)
    df = dm.read_frame("table0")
    df["new_metric"] = [7.0, 8.0]
    dm.write_frame("table0", df)
    after = client.get("/api/tables/table1_a").json()
    assert "new_metric" in after["data"]["names"]
    assert client.get("/api/tree").json()["tables"][0]["n_rows"] == 2


def test_truncated_tsv_serves_stale_copy(run_dir, client):
    first = client.get("/api/tables/table1_a").json()
    path = run_dir / "table1_a.tsv"
    good = path.read_text()
    path.write_text("")  # what to_csv leaves while it is still writing
    stale = client.get("/api/tables/table1_a").json()
    assert stale["data"] == first["data"]
    assert "table1_a" in stale["warning"]
    path.write_text(good.replace("AAA", "WWW"))
    fresh = client.get("/api/tables/table1_a").json()
    assert "warning" not in fresh
    assert "WWW" in fresh["data"]["cols"][fresh["data"]["names"].index("proteinmpnn_sequence")]


def test_serve_parser_defaults(tmp_path):
    args = build_serve_parser().parse_args([str(tmp_path)])
    assert args.run_dir == tmp_path and args.host == "127.0.0.1" and args.port == 8765
    assert args.no_browser is False and args.roots == []
    args = build_serve_parser().parse_args([str(tmp_path), "--roots", "/a", "/b", "--no-browser"])
    assert args.roots == [Path("/a"), Path("/b")] and args.no_browser
