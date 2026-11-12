"""Tests for ``sapia clean``: keeping the rows a filter selects and removing the
rest (rows, or one leaf's cells) with every file that belongs to them."""

import json
from pathlib import Path

import pytest

from prosapia.cli.clean import CLEAN_LOG, CleanArgs, clean_from_args
from prosapia.core import GEN, PARENT_NAME, PARENT_TABLE, DataManager, Table
from prosapia.core.naming import RUN_META_FILENAME, SUBMISSIONS_DIRNAME


def _write(dm: DataManager, table: Table, rows: dict[str, dict]) -> None:
    dm.rm.register_table(table)
    df = dm.read_frame(table.table_name)
    for name, data in rows.items():
        df = dm.update(df, name, data)
    dm.write_frame(table.table_name, df)


def _sub(run_dir: Path, table: str, leaf: str, tool: str | None = None) -> Path:
    """The leaf's first submission dir (created), with a sidecar naming ``tool``."""
    leaf_dir = run_dir / table / leaf
    sub = leaf_dir / SUBMISSIONS_DIRNAME / "00"
    sub.mkdir(parents=True, exist_ok=True)
    (leaf_dir / f"{leaf}_logs").mkdir(exist_ok=True)
    (leaf_dir / RUN_META_FILENAME).write_text(json.dumps({"tool": tool or leaf}))
    return sub


def _file(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return str(path)


def _clean(run_dir, table, leaf=None, **kw):
    clean_from_args(
        CleanArgs(
            run_dir=run_dir,
            table=table,
            leaf=leaf,
            filter=kw.get("filter"),
            where=kw.get("where"),
            descendants=kw.get("descendants", False),
            ancestors=kw.get("ancestors", False),
            dry_run=kw.get("dry_run", False),
        )
    )


def _log(run_dir) -> list[dict]:
    return [json.loads(line) for line in (run_dir / CLEAN_LOG).read_text().splitlines()]


def _campaign(tmp_path):
    """table0 (rfd; S0 kind=keep, S1 kind=drop) -> table1 (mpnn: one fasta and one
    input symlink per parent, shared by its children; score good/bad), with an
    update leaf af3 on table1: per-design result dirs, input jsons and tsvs, plus
    a shard file that belongs to no design."""
    dm = DataManager(tmp_path)
    rfd = _sub(tmp_path, "table0", "rfd")
    _write(
        dm,
        Table("table0", 0, "", None, "rfd"),
        {
            p: {"kind": kind, "rfd_path": _file(rfd / f"{p}.pdb")}
            for p, kind in (("S0", "keep"), ("S1", "drop"))
        },
    )
    mpnn = _sub(tmp_path, "table1", "mpnn")
    af3 = _sub(tmp_path, "table1", "af3")
    _file(af3 / "af3_shards" / "shard_0" / "shard.txt")
    for p in ("S0", "S1"):
        (mpnn / "grp_0" / "inputs").mkdir(parents=True, exist_ok=True)
        (mpnn / "grp_0" / "inputs" / f"{p}.pdb").symlink_to(rfd / f"{p}.pdb")
    rows = {}
    for name, parent, score in (
        ("S0_0", "S0", "good"),
        ("S0_1", "S0", "bad"),
        ("S1_0", "S1", "good"),
    ):
        _file(af3 / "af3_inputs" / f"{name}.json")
        _file(af3 / f"{name}.tsv")
        rows[name] = {
            PARENT_NAME: parent,
            PARENT_TABLE: "table0",
            GEN: 1,
            "score": score,
            "mpnn_status": "OK",
            "mpnn_path": _file(mpnn / "grp_0" / "seqs" / f"{parent}.fa"),
            "af3_status": "OK",
            "af3_plddt": 0.9,
            "af3_path": _file(af3 / "results" / name / f"{name}_model.cif"),
        }
    _write(dm, Table("table1", 1, "", "table0", "mpnn"), rows)
    return dm, mpnn, af3


def test_leaf_clean_blanks_its_cells_and_removes_its_files(tmp_path):
    dm, mpnn, af3 = _campaign(tmp_path)
    _clean(tmp_path, "table1", "af3", where=["score=good"])

    df = dm.read_frame("table1")
    assert list(df.index) == ["S0_0", "S0_1", "S1_0"]
    assert df.loc["S0_1", ["af3_status", "af3_path", "af3_plddt"]].isna().all()
    assert df.at["S0_1", "mpnn_status"] == "OK"
    for gone in ("results/S0_1", "af3_inputs/S0_1.json", "S0_1.tsv"):
        assert not (af3 / gone).exists()
    for kept in ("results/S0_0", "af3_inputs/S0_0.json", "S0_0.tsv"):
        assert (af3 / kept).exists()
    assert (af3 / "af3_shards" / "shard_0" / "shard.txt").is_file()
    assert (mpnn / "grp_0" / "seqs" / "S0.fa").is_file()  # another leaf's file

    (record,) = _log(tmp_path)
    assert record["leaf"] == "af3"
    assert record["removed"] == {"table1": ["S0_1"]}
    assert (record["kept"], record["files"]) == (2, 3)


def test_clean_drops_rows_and_their_files_from_every_leaf(tmp_path):
    dm, mpnn, af3 = _campaign(tmp_path)
    _clean(tmp_path, "table1", where=["score=good"])

    assert list(dm.read_frame("table1").index) == ["S0_0", "S1_0"]
    assert not (af3 / "results" / "S0_1").exists()
    assert not (af3 / "af3_inputs" / "S0_1.json").exists()
    # the parent's files stay while one of its children is kept
    assert (mpnn / "grp_0" / "seqs" / "S0.fa").is_file()
    assert (mpnn / "grp_0" / "inputs" / "S0.pdb").is_symlink()
    assert _log(tmp_path)[0]["removed"] == {"table1": ["S0_1"]}


def test_filter_sees_ancestor_columns_and_the_last_child_takes_the_parent_files(
    tmp_path,
):
    dm, mpnn, af3 = _campaign(tmp_path)
    module = tmp_path / "keep.py"
    module.write_text("def apply_filter(df):\n    return df[df['kind'] == 'keep']\n")
    _clean(tmp_path, "table1", filter=module)

    assert list(dm.read_frame("table1").index) == ["S0_0", "S0_1"]
    assert not (mpnn / "grp_0" / "seqs" / "S1.fa").exists()
    # the input symlink goes, the parent's structure it points to stays
    assert not (mpnn / "grp_0" / "inputs" / "S1.pdb").is_symlink()
    assert (
        tmp_path / "table0" / "rfd" / SUBMISSIONS_DIRNAME / "00" / "S1.pdb"
    ).exists()
    assert _log(tmp_path)[0]["filter"] == str(module)


def _diffusion(tmp_path):
    """Root table0 from one rfdiffusion group P: rows P_1 and P_10, each with its
    pdb (in the table), trb and traj; P/ also holds P's input and marker."""
    dm = DataManager(tmp_path)
    group = _sub(tmp_path, "table0", "rfdiffusion") / "P"
    rows = {}
    for name in ("P_1", "P_10"):
        _file(group / f"{name}.trb")
        _file(group / "traj" / f"{name}_pX0_traj.pdb")
        rows[name] = {
            PARENT_NAME: "P",
            PARENT_TABLE: "root",
            GEN: 0,
            "keep": name,
            "rfdiffusion_path": _file(group / f"{name}.pdb"),
        }
    _file(group / "_diffusion_input" / "P_renumbered.pdb")
    _file(group / "command.txt")
    _write(dm, Table("table0", 0, "", None, "rfdiffusion"), rows)
    return dm, group


def test_children_are_cleaned_one_by_one_and_the_parent_dir_goes_with_the_last(
    tmp_path,
):
    dm, group = _diffusion(tmp_path)
    _clean(tmp_path, "table0", where=["keep=P_10"])

    for gone in ("P_1.pdb", "P_1.trb", "traj/P_1_pX0_traj.pdb"):
        assert not (group / gone).exists()
    for kept in (
        "P_10.pdb",
        "P_10.trb",
        "traj/P_10_pX0_traj.pdb",
        "_diffusion_input/P_renumbered.pdb",
        "command.txt",
    ):
        assert (group / kept).exists()

    _clean(tmp_path, "table0", where=["keep=none"])
    assert dm.read_frame("table0").empty
    assert not group.exists()
    assert group.parent.is_dir()  # the submission dir itself stays


def test_converted_pdbs_go_with_their_source_and_its_sidecar_files(tmp_path):
    dm, _, af3 = _campaign(tmp_path)
    stem = "shard_0_S0_1_0_model_0"
    src = _file(af3 / "results_shard_0" / f"{stem}.cif.gz")
    _file(af3 / "results_shard_0" / f"{stem}.json")
    cache = tmp_path / ".cif_to_pdb"
    pdb = _file(cache / f"{stem}.cif.abcd1234.pdb")
    (cache / f"{stem}.cif.abcd1234.src").write_text(src)
    dm.write_frame(
        "table1", dm.update(dm.read_frame("table1"), "S0_1", {"af3_pdb": pdb})
    )

    _clean(tmp_path, "table1", "af3", where=["score=good"])
    assert not Path(pdb).exists()
    assert not (cache / f"{stem}.cif.abcd1234.src").exists()
    assert not Path(src).exists()
    assert not (af3 / "results_shard_0" / f"{stem}.json").exists()


def test_descendant_rows_are_refused_unless_asked_for(tmp_path):
    dm, _, _ = _campaign(tmp_path)
    _write(
        dm,
        Table("table2", 2, "", "table1", "af2"),
        {
            f"{p}_x": {PARENT_NAME: p, PARENT_TABLE: "table1", GEN: 2}
            for p in ("S0_0", "S0_1")
        },
    )
    with pytest.raises(SystemExit, match="table2.*--descendants"):
        _clean(tmp_path, "table1", where=["score=good"])
    assert len(dm.read_frame("table1")) == 3  # refused before touching anything

    _clean(tmp_path, "table1", where=["score=good"], descendants=True)
    assert list(dm.read_frame("table2").index) == ["S0_0_x"]
    assert _log(tmp_path)[0]["removed"] == {
        "table1": ["S0_1"],
        "table2": ["S0_1_x"],
    }


def test_ancestors_takes_the_parents_left_without_children(tmp_path, capsys):
    """D1 keeps a child, D2 loses its only one, D3 still has one in table1b, D4
    never had any."""
    dm = DataManager(tmp_path)
    rfd = _sub(tmp_path, "table0", "rfd")
    _write(
        dm,
        Table("table0", 0, "", None, "rfd"),
        {d: {"rfd_path": _file(rfd / f"{d}.pdb")} for d in ("D1", "D2", "D3", "D4")},
    )
    child = {PARENT_TABLE: "table0", GEN: 1}
    _write(
        dm,
        Table("table1", 1, "", "table0", "mpnn"),
        {
            "D1_a": {**child, PARENT_NAME: "D1", "pass": "yes"},
            "D1_b": {**child, PARENT_NAME: "D1", "pass": "no"},
            "D2_a": {**child, PARENT_NAME: "D2", "pass": "no"},
            "D3_a": {**child, PARENT_NAME: "D3", "pass": "no"},
        },
    )
    _write(
        dm,
        Table("table1_b", 1, "b", "table0", "mpnn"),
        {"D3_x": {**child, PARENT_NAME: "D3"}},
    )

    _clean(tmp_path, "table1", where=["pass=yes"], ancestors=True)
    assert list(dm.read_frame("table1").index) == ["D1_a"]
    assert list(dm.read_frame("table0").index) == ["D1", "D3", "D4"]
    assert not (rfd / "D2.pdb").exists()
    assert (rfd / "D1.pdb").exists()
    assert (
        "drop 1 row(s) from table0 (left without children)" in capsys.readouterr().out
    )
    assert _log(tmp_path)[0]["removed"]["table0"] == ["D2"]


@pytest.mark.parametrize(
    "leaf, kw, match",
    [
        (None, {}, "--filter or --where"),
        ("mpnn", {"where": ["score=good"]}, "created table 'table1'"),
        ("af3", {"where": ["score=good"], "ancestors": True}, "--leaf keeps the rows"),
        ("nope", {"where": ["score=good"]}, "No leaf 'nope'"),
    ],
)
def test_refusals(tmp_path, leaf, kw, match):
    _campaign(tmp_path)
    with pytest.raises(SystemExit, match=match):
        _clean(tmp_path, "table1", leaf, **kw)


def test_dry_run_touches_nothing(tmp_path, capsys):
    dm, _, af3 = _campaign(tmp_path)
    before = dm.read_frame("table1")
    _clean(tmp_path, "table1", where=["score=good"], dry_run=True)

    out = capsys.readouterr().out
    assert "would keep 2 of 3 row(s) of table1" in out
    assert "would drop 1 row(s) from table1" in out
    assert "would remove 3 file(s)/dir(s)" in out
    assert dm.read_frame("table1").equals(before)
    assert (af3 / "results" / "S0_1").is_dir()
    assert not (tmp_path / CLEAN_LOG).exists()


def test_keeping_every_row_cleans_nothing(tmp_path, capsys):
    dm, _, _ = _campaign(tmp_path)
    before = dm.read_frame("table1")
    _clean(tmp_path, "table1", where=["mpnn_status=OK"])
    assert "nothing to clean" in capsys.readouterr().out
    assert dm.read_frame("table1").equals(before)
    assert not (tmp_path / CLEAN_LOG).exists()


def test_each_clean_appends_to_the_log(tmp_path):
    _campaign(tmp_path)
    _clean(tmp_path, "table1", "af3", where=["score=good"])
    _clean(tmp_path, "table1", where=["score=good"])
    assert [r["leaf"] for r in _log(tmp_path)] == ["af3", None]
