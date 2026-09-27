"""Tests for the shared position mini-language and the predictor chain-map builder."""

import pytest

from prosapia.utils import build_chain_map, parse_chain_positions, parse_positions

# Stub lineage lookup: (name, column) -> value.
_COLUMNS = {"prebundle_length": 3, "motif_end": 5}


def _lookup(name, column):
    return _COLUMNS.get(column)


# --------------------------- parse_chain_positions ---------------------------


def test_single_positions_and_ranges():
    assert parse_chain_positions("1,3,5:7") == [1, 3, 5, 6, 7]


def test_order_preserved_not_deduped():
    # tied positions rely on index-parallel, order-preserving, non-deduped output
    assert parse_chain_positions("3,1,1:2") == [3, 1, 1, 2]


def test_open_ended_ranges_with_length():
    assert parse_chain_positions("3:", length=5) == [3, 4, 5]
    assert parse_chain_positions(":3", length=5) == [1, 2, 3]
    assert parse_chain_positions(":", length=4) == [1, 2, 3, 4]


def test_open_ended_without_length_raises():
    with pytest.raises(ValueError):
        parse_chain_positions("3:", length=None)


def test_malformed_range_raises():
    with pytest.raises(ValueError):
        parse_chain_positions("1:2:3")


def test_position_past_chain_end_raises():
    with pytest.raises(ValueError):
        parse_chain_positions("1:100", length=5)


def test_non_positive_position_raises():
    # would otherwise wrap to the C-terminus via negative indexing
    with pytest.raises(ValueError):
        parse_chain_positions("0:3", length=5)


def test_out_of_bounds_unchecked_without_length():
    # proteinmpnn path (length=None) leaves bounds to the caller
    assert parse_chain_positions("1:100") == list(range(1, 101))


def test_non_integer_raises():
    with pytest.raises(ValueError):
        parse_chain_positions("abc")


# ------------------------------ parse_positions ------------------------------


def test_empty_spec_is_empty_list():
    assert parse_positions("", _lookup, "d") == []


def test_chain_groups_split_on_slash():
    assert parse_positions("1:3/5,6", _lookup, "d") == [[1, 2, 3], [5, 6]]


def test_brace_island_resolved_up_lineage():
    # {motif_end} -> 5, so 1:{motif_end} -> 1..5
    assert parse_positions("1:{motif_end}", _lookup, "d") == [[1, 2, 3, 4, 5]]


def test_outer_brackets_optional():
    assert parse_positions("[1:2/3]", _lookup, "d") == [[1, 2], [3]]


def test_lengths_resolve_open_ends_per_group():
    assert parse_positions("2:/:2", _lookup, "d", lengths=[4, 3]) == [[2, 3, 4], [1, 2]]


# ------------------------------ build_chain_map ------------------------------

SEQ = "AAAA/BBB"  # chain A = AAAA, chain B = BBB


def test_no_positions_returns_selected_chains():
    assert build_chain_map(SEQ, None, None, _lookup, "d") == {"A": "AAAA", "B": "BBB"}
    assert build_chain_map(SEQ, None, "none", _lookup, "d") == {"A": "AAAA", "B": "BBB"}


def test_positions_keeps_selected_residues():
    # keep A[1:2] and B[2:3] (1-indexed, inclusive)
    assert build_chain_map(SEQ, None, "1:2/2:3", _lookup, "d") == {"A": "AA", "B": "BB"}


def test_single_group_broadcasts_to_all_chains():
    # {prebundle_length+1}: -> 4: (prefix trim), applied to every chain
    assert build_chain_map(SEQ, None, "{prebundle_length+1}:", _lookup, "d") == {
        "A": "A",
        "B": "",
    }


def test_non_contiguous_fragments_concatenate():
    seq = "ABCDEF"
    assert build_chain_map(seq, None, "1,4:6", _lookup, "d") == {"A": "ADEF"}


def test_group_count_mismatch_raises():
    with pytest.raises(ValueError):
        build_chain_map(SEQ, None, "1:2/1:2/1:2", _lookup, "d")


def test_positions_respect_chain_selection():
    # only chain A selected, single-group spec broadcasts to it
    assert build_chain_map(SEQ, "A", "1:2", _lookup, "d") == {"A": "AA"}
