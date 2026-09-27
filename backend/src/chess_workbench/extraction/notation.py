"""Source score annotations that remain distinct from authoritative SAN."""

from __future__ import annotations

import re

from .contracts import MoveNode

NAG_OVERRIDE_EXTENSION = "chess-workbench.nag-override"

_PUNCTUATION_NAGS = {
    "!": 1,
    "?": 2,
    "!!": 3,
    "??": 4,
    "!?": 5,
    "?!": 6,
}
_SOURCE_SUFFIX = re.compile(r"(!!|\?\?|!\?|\?!|!|\?)\s*$")


def source_punctuation_nag(move_text: str) -> int | None:
    """Read a printed move's trailing !/? without changing its source text."""
    match = _SOURCE_SUFFIX.search(move_text)
    return _PUNCTUATION_NAGS[match.group(1)] if match else None


def effective_move_nags(node: MoveNode) -> list[int]:
    """Structured NAGs win; old review packages can still use their source suffix."""
    if node.nags or node.extensions.get(NAG_OVERRIDE_EXTENSION) is True:
        return node.nags
    source_nag = source_punctuation_nag(node.move_text)
    return [source_nag] if source_nag is not None else []
