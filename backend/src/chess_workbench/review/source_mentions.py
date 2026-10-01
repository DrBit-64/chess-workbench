"""Read-only notation candidates for source-to-score review highlighting."""

from __future__ import annotations

import re
from typing import Any

from chess_workbench.extraction.prompting import CcefPromptContext
from chess_workbench.extraction.relations import source_tokens


def source_move_mentions(context: CcefPromptContext) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Keep source coordinates; these candidates do not assert a played move."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for source_token in source_tokens(context):
        grouped.setdefault((source_token.page, source_token.order), []).append(
            {"start": source_token.start, "end": source_token.end, "kind": "candidate"}
        )
    for page in context.pages:
        previous = ""
        for entry in page.fragments:
            text = entry.fragment.text
            mentions = grouped.setdefault((page.physical_page, entry.order), [])
            # h7-h6 is one plan/move reference, not two missing pawn moves.
            for match in re.finditer(r"\b[KQRBN]?[a-h][1-8][-–][a-h][1-8][+#]?[!?]*", text):
                mentions[:] = [
                    token
                    for token in mentions
                    if token["end"] <= match.start() or token["start"] >= match.end()
                ]
                mentions.append({"start": match.start(), "end": match.end(), "kind": "candidate"})
            for token in mentions:
                raw = text[token["start"] : token["end"]]
                if re.fullmatch(r"[a-h][1-8]", raw) is None:
                    continue
                before = previous + " " + text[: token["start"]]
                after = text[token["end"] :]
                if re.search(
                    r"\b(?:on|at|via|weakens|controls|protects|attacks|guards|covers)\s+$",
                    before,
                    re.I,
                ) or re.match(r"-(?:square|bishop|knight|rook|queen|king|pawn)\b", after, re.I):
                    token["kind"] = "square"
            mentions.sort(key=lambda token: token["start"])
            previous = text if entry.fragment.origin != "diagram" else ""
    return grouped
