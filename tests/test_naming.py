"""Tests for tool_leaf and resolve_dir_name (the nested dir / column convention)."""

from argparse import Namespace

import pytest

from prosapia.core import Database, ToolMetadata, build_tool_leaf, resolve_dir_name


def test_tool_leaf():
    assert build_tool_leaf("alphafold3") == "alphafold3"
    assert build_tool_leaf("alphafold3", "seed42") == "alphafold3_seed42"
    assert build_tool_leaf("boltz", "") == "boltz"


def _args(run_dir, *, dir_label=""):
    return Namespace(run_dir=run_dir, dir_label=dir_label)


def test_resolve_dir_name_update(tmp_path):
    # The leaf is keyed by the *running* tool, not the db's creating tool: an update
    # tool annotating a worms-created db writes to run_dir/<db>/<update_tool>/.
    d = tmp_path / "db2_worms" / "alphafold3"
    d.mkdir(parents=True)
    db = Database(db_name="db2_worms", tool_name="worms")  # creator != running tool
    assert resolve_dir_name(_args(tmp_path), db, ToolMetadata("alphafold3", "update")) == d


def test_resolve_dir_name_with_label(tmp_path):
    d = tmp_path / "db2_worms" / "alphafold3_seed42"
    d.mkdir(parents=True)
    db = Database(db_name="db2_worms")
    args = _args(tmp_path, dir_label="seed42")
    assert resolve_dir_name(args, db, ToolMetadata("alphafold3", "update")) == d


def test_resolve_dir_name_create_uses_child(tmp_path):
    # For a create tool the run script reserved the child db and keyed the output
    # dir by its name, so collect resolves the dir under the child db name.
    d = tmp_path / "db1_worms_hl" / "mpnn"
    d.mkdir(parents=True)
    db = Database(db_name="db1_worms_hl")
    assert resolve_dir_name(_args(tmp_path), db, ToolMetadata("mpnn", "create")) == d


def test_resolve_dir_name_missing_dir(tmp_path):
    db = Database(db_name="db2_worms")
    with pytest.raises(FileNotFoundError):
        resolve_dir_name(_args(tmp_path), db, ToolMetadata("alphafold3", "update"))


def test_resolve_dir_name_must_exist_false(tmp_path):
    # The run script computes the path before creating it -> no existence guard.
    db = Database(db_name="db2_worms")
    expected = tmp_path / "db2_worms" / "alphafold3"
    got = resolve_dir_name(_args(tmp_path), db, ToolMetadata("alphafold3", "update"), must_exist=False)
    assert got == expected
