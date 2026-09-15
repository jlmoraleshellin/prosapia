"""Position mini-language: per-chain residue selection.

Shared by proteinmpnn (fixed/tied position lists) and the structure predictors
(the ``--positions`` residue selector). The grammar: ``/`` breaks chains, ``,``
separates fragments within a chain, ``start:end`` expands inclusively, a single
position passes through; ``{...}`` islands hold table-column expressions resolved
up the lineage (see ``prosapia.utils.expr``); outer ``[...]`` is optional.

Positions are 1-indexed within each chain. Order is preserved and NOT
de-duplicated. Open-ended ranges (``10:`` / ``:50`` / bare ``:``) resolve their
missing endpoint against a known chain length; without a length they raise (as in
proteinmpnn, which never uses them).
"""

from typing import cast

from ..core.data_manager import LookupFn
from .expr import resolve_template


def _pos_int(tok: str, token: str, name: str) -> int:
    """Parse a resolved position endpoint to int with a migration-friendly error."""
    try:
        return int(tok)
    except ValueError:
        raise ValueError(
            f"design {name!r}: non-integer position {tok!r} in {token!r} "
            f"(wrap table column expressions in braces, e.g. '{{motif_end}}')"
        )


def parse_chain_positions(
    chain_spec: str, *, length: int | None = None, name: str = ""
) -> list[int]:
    """Expand one chain's position mini-language into a 1-indexed position list.

    ``chain_spec`` is a single chain group with ``{...}`` islands already
    resolved: ``,`` separates fragments, ``start:end`` expands inclusively, a
    single position passes through. Order is preserved and NOT de-duplicated.

    Open-ended ranges resolve against ``length``: ``10:`` -> ``10..length``,
    ``:50`` -> ``1..50``, bare ``:`` -> ``1..length``. An open end when
    ``length`` is ``None`` raises ``ValueError``. When ``length`` is known,
    positions must fall within ``1..length`` -- an out-of-bounds endpoint raises
    (rather than crashing on a slice or silently wrapping via negative indexing).
    Only a malformed range token (more than one ``:``) is otherwise rejected;
    with ``length is None`` (e.g. proteinmpnn) bounds are left to the caller.
    """
    positions: list[int] = []
    for token in chain_spec.split(","):
        token = token.strip()
        if not token:
            continue
        ends = token.split(":")
        if len(ends) == 1:
            start = end = _pos_int(ends[0], token, name)
        elif len(ends) == 2:
            lo, hi = ends[0].strip(), ends[1].strip()
            if (not lo or not hi) and length is None:
                raise ValueError(
                    f"design {name!r}: open-ended range {token!r} needs a known "
                    f"chain length (not available here)"
                )
            start = _pos_int(lo, token, name) if lo else 1
            # a missing endpoint is only reached when length is not None (guarded above)
            end = _pos_int(hi, token, name) if hi else cast(int, length)
        else:
            raise ValueError(
                f"design {name!r}: malformed position range {token!r} "
                f"(expected 'start:end' or a single position)"
            )
        if length is not None and (start < 1 or end > length):
            raise ValueError(
                f"design {name!r}: position {token!r} is out of bounds for a chain "
                f"of length {length} (positions are 1..{length})"
            )
        positions.extend(range(start, end + 1))
    return positions


def parse_positions(
    spec: str,
    lookup: LookupFn,
    name: str,
    *,
    lengths: list[int] | None = None,
) -> list[list[int]]:
    """Expand the full position mini-language into per-chain position lists.

    Resolves ``{...}`` islands via ``resolve_template`` (integers, bare table
    column names, and ``+ - * //`` up the lineage for ``name``), strips an outer
    ``[...]``, then splits on ``/`` into per-chain groups and delegates each to
    ``parse_chain_positions``. When ``lengths`` is given, group *i* resolves its
    open-ended ranges against ``lengths[i]``. Empty spec -> ``[]``.
    """
    spec = resolve_template(spec, lookup, name).strip().strip("[]").strip()
    if not spec:
        return []
    groups = spec.split("/")
    return [
        parse_chain_positions(
            group,
            length=lengths[i] if lengths is not None else None,
            name=name,
        )
        for i, group in enumerate(groups)
    ]
