"""Chain mini-language and proteinmpnn-sequence chain selection.

The chain mini-language (``A:D`` -> A, B, C, D) is shared by every tool that
selects chains: proteinmpnn (which chains to design) and the structure
predictors (which chains to predict). The predictors additionally map a
proteinmpnn ``/``-chainbreak sequence onto chain letters and group chains that
share a sequence, so homo- and hetero-oligomers fall out of one code path.
"""

import string


def expand_chain_spec(spec: str) -> list[str]:
    """Expand the chain mini-language into an ordered list of chain letters.

    ``:`` is an inclusive letter range and ``,`` separates: ``A:C,E`` ->
    ``["A", "B", "C", "E"]``. Order is preserved (no sort/dedupe). Outer ``[...]``
    brackets and surrounding whitespace are optional. Empty spec -> ``[]``.
    """
    spec = spec.strip().strip("[]").strip()
    if not spec:
        return []

    chains: list[str] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        ends = [e.strip() for e in token.split(":")]
        if len(ends) == 1:
            start = end = ends[0]
        elif len(ends) == 2:
            start, end = ends
        else:
            raise ValueError(
                f"malformed chain range {token!r} (expected 'A' or 'A:C')"
            )
        if not (
            len(start) == 1 and len(end) == 1 and start.isalpha() and end.isalpha()
        ):
            raise ValueError(
                f"chain range {token!r} must use single letters (e.g. 'A:C')"
            )
        lo, hi = ord(start.upper()), ord(end.upper())
        if hi < lo:
            raise ValueError(f"chain range {token!r} ends before it starts")
        chains.extend(chr(c) for c in range(lo, hi + 1))
    return chains


def select_chains(sequence: str, chains_spec: str | None) -> dict[str, str]:
    """Map the chains to predict from a proteinmpnn ``/``-chainbreak sequence.

    Segment *i* of the ``/``-separated sequence is chain letter ``chr(ord('A') + i)``.
    Without a spec, every chain in the sequence is selected. With a spec (chain
    mini-language, e.g. ``A:D``), only the requested letters that actually exist
    in the sequence are kept -- letters beyond the sequence's chain count are
    dropped (predict all available). Returns an ordered ``{letter: sequence}`` map.
    """
    segments = [seg.strip() for seg in sequence.split("/")]
    letters = list(string.ascii_uppercase[: len(segments)])
    seq_by_letter = dict(zip(letters, segments))
    if not chains_spec:
        selected = letters
    else:
        selected = [c for c in expand_chain_spec(chains_spec) if c in seq_by_letter]
    return {c: seq_by_letter[c] for c in selected}


def group_by_sequence(chain_map: dict[str, str]) -> list[tuple[list[str], str]]:
    """Group chains that share an identical sequence, preserving first-seen order.

    A homo-oligomer collapses to a single group (one entity, many chain letters);
    a hetero-oligomer yields one group per distinct sequence. Returns a list of
    ``(letters, sequence)`` pairs.
    """
    groups: dict[str, list[str]] = {}
    for letter, seq in chain_map.items():
        # setting the sequence as a dict key converts the problem from a pairwise matching into a near-constant-time bucket lookup
        groups.setdefault(seq, []).append(letter)
    return [(letters, seq) for seq, letters in groups.items()]
