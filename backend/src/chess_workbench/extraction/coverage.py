"""Source-bound coverage checks and additive repair for missed move variations.

The semantic extractor remains responsible for understanding prose.  This module
only identifies conspicuous, numbered notation in trusted OCR evidence and asks
for a bounded additive supplement. Local code resolves parent positions with
python-chess and proves that existing nodes, annotations and reading-flow
entries remain byte-for-byte equivalent while every new node cites evidence
involved in a reported gap.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Sequence
from typing import Annotated, Literal, Self

import chess
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .contracts import (
    AnnotationFlowRef,
    EvidenceRef,
    ExtractionPackageV1_1,
    MoveFlowRef,
    MoveNode,
    MoveSequenceItemV1_1,
    Sha256Hex,
)
from .decoder import CcefDecodeError, _parse_payload
from .prompting import CcefPromptContext, PromptEvidenceFragment
from .provider import StructuredGenerationRequest, StructuredGenerationResponse, StructuredMessage

CCEF_COVERAGE_SUPPLEMENT_SCHEMA = "chess-workbench/ccef-coverage-supplement/1.0"
_SUPPLEMENT_SCHEMA_NAME = "chess_workbench_ccef_coverage_supplement_v1"
_MAX_GAPS = 16
_MAX_REPLACEMENTS = 8
_MAX_ADDED_NODES = 128
_MAX_OUTPUT_TOKENS = 8_192

_NUMBER = re.compile(r"(?<![0-9A-Za-z])(\d{1,3})(\.\.\.|\.)\s*")
_SAN = re.compile(
    r"(?:O-O(?:-O)?|0-0(?:-0)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)[!?]{0,2}"
)
_NAG_SUFFIX = re.compile(r"[!?]{1,2}$")
_MOVE_PREFIX = re.compile(r"^\d{1,3}(?:\.\.\.|\.)")
_TRAILING_NOTATION = re.compile(r"^[\s,;:()\[\]{}.!?\-–—]*$")
_CONNECTOR = re.compile(
    r"^[\s,;:()\[\]{}.!?\-–—]*(?:(?:after|because|of|there|would|follow|then|and|"
    r"if|by|was|is|with)\s+)*[\s,;:()\[\]{}.!?\-–—]*$",
    re.IGNORECASE,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CcefCoverageMove(_StrictModel):
    move_number: Annotated[int, Field(ge=1, le=999)]
    side_to_move: Literal["w", "b"]
    move_text: Annotated[str, Field(min_length=1, max_length=100)]


class CcefCoverageEvidence(_StrictModel):
    physical_page: Annotated[int, Field(ge=1, le=20_000)]
    order: Annotated[int, Field(ge=0)]
    fragment_sha256: Sha256Hex
    text: Annotated[str, Field(min_length=1, max_length=200_000)]


class CcefCoverageGap(_StrictModel):
    gap_id: str = Field(pattern=r"^coverage-gap-[1-9][0-9]*$", max_length=40)
    physical_page: Annotated[int, Field(ge=1, le=20_000)]
    source_text: Annotated[str, Field(min_length=1, max_length=8_000)]
    moves: list[CcefCoverageMove] = Field(min_length=1, max_length=64)
    trusted_evidence: list[CcefCoverageEvidence] = Field(min_length=1, max_length=3)
    candidate_sequence_ids: list[str] = Field(min_length=1, max_length=_MAX_REPLACEMENTS)


class CcefCoverageReport(_StrictModel):
    gaps: list[CcefCoverageGap] = Field(default_factory=list, max_length=_MAX_GAPS)


class CcefCoverageAddition(_StrictModel):
    addition_id: str = Field(pattern=r"^addition-[1-9][0-9]*$", max_length=32)
    resolves: list[str] = Field(min_length=1, max_length=_MAX_GAPS)
    sequence_id: str = Field(min_length=1, max_length=128)
    parent_node_id: str | None = Field(default=None, min_length=1, max_length=128)
    insert_after_flow_id: str | None = Field(default=None, min_length=1, max_length=128)
    moves: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def gap_references_are_unique(self) -> Self:
        if len(self.resolves) != len(set(self.resolves)):
            raise ValueError("coverage addition gap references must be unique")
        return self


class CcefCoverageSupplement(_StrictModel):
    supplement_schema: Literal["chess-workbench/ccef-coverage-supplement/1.0"]
    base_response_sha256: Sha256Hex
    resolves: list[str] = Field(min_length=1, max_length=_MAX_GAPS)
    additions: list[CcefCoverageAddition] = Field(min_length=1, max_length=_MAX_GAPS)

    @model_validator(mode="after")
    def references_are_unique(self) -> Self:
        if len(self.resolves) != len(set(self.resolves)):
            raise ValueError("coverage gap references must be unique")
        addition_ids = [addition.addition_id for addition in self.additions]
        if len(addition_ids) != len(set(addition_ids)):
            raise ValueError("coverage addition ids must be unique")
        addition_resolves = [gap for addition in self.additions for gap in addition.resolves]
        if len(addition_resolves) != len(set(addition_resolves)):
            raise ValueError("coverage gaps must be assigned to one addition")
        if set(addition_resolves) != set(self.resolves):
            raise ValueError("coverage additions must cover top-level resolves exactly")
        return self


class CcefCoverageError(ValueError):
    """Fixed, non-sensitive failure raised by the coverage boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _response_sha256(response: StructuredGenerationResponse) -> str:
    return hashlib.sha256(response.content.encode("utf-8")).hexdigest()


def _normalized_move_text(value: str) -> str:
    value = _NAG_SUFFIX.sub("", value.strip())
    value = _MOVE_PREFIX.sub("", value)
    return value.replace("0-0-0", "O-O-O").replace("0-0", "O-O")


def _parse_immediate_line(
    text: str, number_match: re.Match[str]
) -> tuple[list[CcefCoverageMove], int]:
    number = int(number_match.group(1))
    side: Literal["w", "b"] = "b" if number_match.group(2) == "..." else "w"
    moves: list[CcefCoverageMove] = []
    position = number_match.end()
    while position < len(text):
        san_match = _SAN.match(text, position)
        if san_match is None:
            break
        moves.append(
            CcefCoverageMove(
                move_number=number,
                side_to_move=side,
                move_text=san_match.group(0),
            )
        )
        position = san_match.end()
        if side == "w":
            side = "b"
        else:
            side = "w"
            number += 1
        whitespace_end = position
        while whitespace_end < len(text) and text[whitespace_end].isspace():
            whitespace_end += 1
        next_number = _NUMBER.match(text, whitespace_end)
        if next_number is not None:
            number = int(next_number.group(1))
            side = "b" if next_number.group(2) == "..." else "w"
            position = next_number.end()
            continue
        if whitespace_end == position:
            break
        position = whitespace_end
    return moves, position


def _inside_parentheses(text: str, start: int, end: int) -> bool:
    opening = text.rfind("(", 0, start + 1)
    closing_before = text.rfind(")", 0, start + 1)
    if opening <= closing_before:
        return False
    closing_after = text.find(")", end)
    return closing_after >= end


def _parenthesis_depth(text: str, position: int) -> int:
    depth = 0
    for character in text[:position]:
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
    return depth


def _notation_candidates(text: str) -> list[tuple[int, int, list[CcefCoverageMove]]]:
    """Return conservative numbered-score spans without interpreting prose moves."""

    segments: list[tuple[int, int, list[CcefCoverageMove]]] = []
    consumed_until = 0
    for marker in _NUMBER.finditer(text):
        if marker.start() < consumed_until:
            continue
        moves, end = _parse_immediate_line(text, marker)
        if not moves:
            continue
        start = marker.start()
        # Merge another explicitly numbered segment only across short chess-text
        # connectors. This covers "because of 41.Nd8" and "after 38...Kg6"
        # without collecting unnumbered plan moves from ordinary prose.
        cursor = end
        while next_marker := _NUMBER.search(text, cursor):
            connector = text[cursor : next_marker.start()]
            if (
                len(connector) > 48
                or _CONNECTOR.fullmatch(connector) is None
                or _parenthesis_depth(text, start) != _parenthesis_depth(text, next_marker.start())
            ):
                break
            following, following_end = _parse_immediate_line(text, next_marker)
            if not following:
                break
            moves.extend(following)
            end = following_end
            cursor = following_end
        fragment_like_score = _TRAILING_NOTATION.fullmatch(text[:start]) is not None and (
            _TRAILING_NOTATION.fullmatch(text[end:]) is not None
        )
        explicitly_annotated = any(_NAG_SUFFIX.search(move.move_text) for move in moves)
        if (
            len(moves) >= 2
            or _inside_parentheses(text, start, end)
            or fragment_like_score
            or explicitly_annotated
        ):
            segments.append((start, end, moves))
            consumed_until = end
    return segments


def _path_covers(sequence: MoveSequenceItemV1_1, moves: Sequence[CcefCoverageMove]) -> bool:
    children: dict[str | None, list[MoveNode]] = {}
    for node in sequence.nodes:
        children.setdefault(node.parent_id, []).append(node)
    flow_ids = [entry.node_id for entry in sequence.reading_flow if isinstance(entry, MoveFlowRef)]
    flow_positions = {node_id: index for index, node_id in enumerate(flow_ids)}

    def matches(node: MoveNode, move: CcefCoverageMove) -> bool:
        candidate = node.san_candidate or node.move_text
        side = node.side_to_move
        move_number = node.move_number
        prefix = _NUMBER.match(node.move_text)
        if move_number is None and prefix is not None:
            move_number = int(prefix.group(1))
        if side is None and node.fen_before is not None:
            fields = node.fen_before.split()
            if len(fields) == 6 and fields[1] in {"w", "b"}:
                side = "w" if fields[1] == "w" else "b"
                if move_number is None and fields[5].isdigit():
                    move_number = int(fields[5])
        if side is None and prefix is not None:
            side = "b" if prefix.group(2) == "..." else "w"
        return (
            _normalized_move_text(candidate) == _normalized_move_text(move.move_text)
            and move_number == move.move_number
            and side == move.side_to_move
        )

    for first in sequence.nodes:
        if not matches(first, moves[0]):
            continue
        path = [first]
        for move in moves[1:]:
            next_node = next(
                (node for node in children.get(path[-1].id, []) if matches(node, move)),
                None,
            )
            if next_node is None:
                break
            path.append(next_node)
        if len(path) == len(moves):
            positions = [flow_positions.get(node.id, -1) for node in path]
            if all(position >= 0 for position in positions) and positions == sorted(positions):
                return True
    return False


def _sequence_candidates(
    package: ExtractionPackageV1_1,
    physical_page: int,
) -> list[str]:
    sequences = [item for item in package.items if isinstance(item, MoveSequenceItemV1_1)]
    exact = [
        sequence.id
        for sequence in sequences
        if any(reference.page == physical_page for reference in sequence.evidence)
        or any(
            reference.page == physical_page
            for node in sequence.nodes
            for reference in node.evidence
        )
    ]
    if exact:
        return exact[:_MAX_REPLACEMENTS]
    nearby = [
        sequence.id
        for sequence in sequences
        if any(abs(reference.page - physical_page) <= 1 for reference in sequence.evidence)
        or any(
            abs(reference.page - physical_page) <= 1
            for node in sequence.nodes
            for reference in node.evidence
        )
    ]
    return nearby[:_MAX_REPLACEMENTS] or [sequence.id for sequence in sequences[:_MAX_REPLACEMENTS]]


def _coverage_evidence(
    fragments: Sequence[PromptEvidenceFragment],
    index: int,
) -> list[CcefCoverageEvidence]:
    result: list[CcefCoverageEvidence] = []
    for selected in range(max(0, index - 1), min(len(fragments), index + 2)):
        entry = fragments[selected]
        fragment = entry.fragment
        if not fragment.text.strip():
            continue
        result.append(
            CcefCoverageEvidence(
                physical_page=fragment.physical_page,
                order=entry.order,
                fragment_sha256=fragment.fragment_sha256,
                text=fragment.text,
            )
        )
    return result


def inspect_ccef_move_coverage(
    package: ExtractionPackageV1_1,
    context: CcefPromptContext,
) -> CcefCoverageReport:
    """Find conspicuous numbered score spans absent from nodes/reading_flow."""

    if type(package) is not ExtractionPackageV1_1:
        raise TypeError("package must be ExtractionPackageV1_1")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    gaps: list[CcefCoverageGap] = []
    sequences = [item for item in package.items if isinstance(item, MoveSequenceItemV1_1)]
    for page in context.pages:
        for fragment_index, entry in enumerate(page.fragments):
            text = entry.fragment.text
            for start, end, moves in _notation_candidates(text):
                if any(_path_covers(sequence, moves) for sequence in sequences):
                    continue
                candidate_ids = _sequence_candidates(package, page.physical_page)
                if not candidate_ids or len(gaps) >= _MAX_GAPS:
                    continue
                gaps.append(
                    CcefCoverageGap(
                        gap_id=f"coverage-gap-{len(gaps) + 1}",
                        physical_page=page.physical_page,
                        source_text=text[max(0, start - 160) : min(len(text), end + 160)],
                        moves=moves,
                        trusted_evidence=_coverage_evidence(page.fragments, fragment_index),
                        candidate_sequence_ids=candidate_ids,
                    )
                )
    return CcefCoverageReport(gaps=gaps)


_SUPPLEMENT_SYSTEM = """\
Complete only the missing numbered chess variations described by the supplied coverage gaps.
Return only small additive instructions; never copy or regenerate an existing sequence or the
document. For each missing line choose one candidate sequence and an existing reading-flow id
after which the source line belongs. moves contains only the printed move tokens in order. The
parent_node_id is only a hint: use an existing node id when certain, otherwise null; local chess
validation resolves the actual parent and does not trust this hint. One addition may
resolve adjacent gaps when the supplied evidence shows one continuous line; include necessary
preceding moves from neighboring supplied evidence when a gap begins in the middle of a legal
branch. Do not turn isolated prose plans into moves. Local code owns node IDs, sibling order,
evidence, reading-flow construction, CCEF validation and chess validation, and will reject an
incorrect sequence/parent/insertion choice or any remaining coverage gap.
"""


def build_ccef_coverage_supplement_request(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
    report: CcefCoverageReport,
    authority_package: ExtractionPackageV1_1,
) -> StructuredGenerationRequest:
    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    if type(report) is not CcefCoverageReport:
        raise TypeError("report must be CcefCoverageReport")
    if type(authority_package) is not ExtractionPackageV1_1:
        raise TypeError("authority_package must be ExtractionPackageV1_1")
    if not report.gaps:
        raise CcefCoverageError("coverage_complete", "CCEF move coverage has no gaps")
    try:
        package = ExtractionPackageV1_1.model_validate(_parse_payload(response))
    except (CcefDecodeError, ValidationError):
        raise CcefCoverageError(
            "invalid_base", "CCEF coverage supplement base is invalid"
        ) from None
    wanted_ids = {sequence_id for gap in report.gaps for sequence_id in gap.candidate_sequence_ids}
    authority_sequences = {
        item.id: item for item in authority_package.items if isinstance(item, MoveSequenceItemV1_1)
    }
    affected = [
        {
            "sequence_id": item.id,
            "title": item.title,
            "initial_position": authority_sequences[item.id].initial_position.model_dump(
                mode="json"
            ),
            "nodes": [
                {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "move_text": node.move_text,
                    "move_number": node.move_number,
                    "side_to_move": node.side_to_move,
                    "validation_status": node.validation_status,
                    "fen_after": node.fen_after,
                }
                for node in authority_sequences[item.id].nodes
            ],
            "reading_flow": [
                {
                    "kind": entry.kind,
                    "id": entry.node_id if isinstance(entry, MoveFlowRef) else entry.annotation_id,
                }
                for entry in authority_sequences[item.id].reading_flow
            ],
        }
        for item in package.items
        if (
            isinstance(item, MoveSequenceItemV1_1)
            and item.id in wanted_ids
            and item.id in authority_sequences
        )
    ]
    trusted_fragments: dict[tuple[int, str], dict[str, object]] = {}
    gaps: list[dict[str, object]] = []
    for gap in report.gaps:
        selectors: list[dict[str, object]] = []
        for evidence in gap.trusted_evidence:
            key = (evidence.physical_page, evidence.fragment_sha256)
            trusted_fragments.setdefault(key, evidence.model_dump(mode="json"))
            selectors.append(
                {
                    "physical_page": evidence.physical_page,
                    "fragment_sha256": evidence.fragment_sha256,
                }
            )
        gaps.append(
            {
                "gap_id": gap.gap_id,
                "physical_page": gap.physical_page,
                "source_text": gap.source_text,
                "moves": [move.model_dump(mode="json") for move in gap.moves],
                "trusted_evidence": selectors,
                "candidate_sequence_ids": gap.candidate_sequence_ids,
            }
        )
    case = {
        "supplement_protocol": CCEF_COVERAGE_SUPPLEMENT_SCHEMA,
        "base_response_sha256": _response_sha256(response),
        "coverage_gaps": gaps,
        "trusted_evidence_fragments": list(trusted_fragments.values()),
        "compact_sequence_index": affected,
        "rules": {
            "existing_content_is_immutable": True,
            "return_only_additive_instructions": True,
            "insertion_id_must_exist_in_the_selected_sequence": True,
            "parent_id_is_only_an_advisory_hint": True,
            "every_gap_must_be_resolved_exactly_once": True,
        },
    }
    encoded = _canonical_json(case)
    if len(encoded) > context.max_prompt_chars:
        raise CcefCoverageError(
            "coverage_too_large", "CCEF coverage supplement prompt exceeds configured limit"
        )
    return StructuredGenerationRequest(
        messages=[
            StructuredMessage(role="system", content=_SUPPLEMENT_SYSTEM),
            StructuredMessage(role="user", content=encoded),
        ],
        response_schema_name=_SUPPLEMENT_SCHEMA_NAME,
        response_schema=CcefCoverageSupplement.model_json_schema(),
        max_output_tokens=min(context.max_output_tokens, _MAX_OUTPUT_TOKENS),
    )


def _flow_identity(entry: MoveFlowRef | AnnotationFlowRef) -> str:
    if isinstance(entry, MoveFlowRef):
        return entry.node_id
    return entry.annotation_id


def _generated_node_id(
    base_sha256: str,
    addition_id: str,
    move_index: int,
    used_ids: set[str],
) -> str:
    digest = hashlib.sha256(f"{base_sha256}:{addition_id}:{move_index}".encode()).hexdigest()[:16]
    candidate = f"coverage-{digest}"
    suffix = 1
    while candidate in used_ids:
        suffix += 1
        candidate = f"coverage-{digest}-{suffix}"
    used_ids.add(candidate)
    return candidate


def _sequence_initial_board(sequence: MoveSequenceItemV1_1) -> chess.Board | None:
    initial = sequence.initial_position
    try:
        if initial.kind == "startpos":
            return chess.Board()
        return chess.Board(initial.fen, chess960=False)
    except ValueError:
        return None


def _play_line(board: chess.Board, moves: Sequence[str]) -> list[chess.Board] | None:
    positions: list[chess.Board] = []
    working = board.copy()
    for move_text in moves:
        try:
            move = working.parse_san(_normalized_move_text(move_text))
        except ValueError:
            return None
        if move == chess.Move.null():
            return None
        working.push(move)
        positions.append(working.copy())
    return positions


def _expected_first_context(
    addition: CcefCoverageAddition,
    gaps_by_id: dict[str, CcefCoverageGap],
) -> tuple[int, Literal["w", "b"]] | None:
    first = _normalized_move_text(addition.moves[0])
    contexts = {
        (move.move_number, move.side_to_move)
        for gap_id in addition.resolves
        for move in gaps_by_id[gap_id].moves[:1]
        if _normalized_move_text(move.move_text) == first
    }
    if len(contexts) == 1:
        return next(iter(contexts))
    prefix = _NUMBER.match(addition.moves[0])
    if prefix is None:
        return None
    return int(prefix.group(1)), "b" if prefix.group(2) == "..." else "w"


def _candidate_parent(
    addition: CcefCoverageAddition,
    gaps_by_id: dict[str, CcefCoverageGap],
    positions: dict[str | None, chess.Board],
    position_ranks: dict[str | None, tuple[int, int]],
    insertion_position: int,
    hint_aliases: dict[str, str],
) -> tuple[str | None, list[chess.Board]] | None:
    expected = _expected_first_context(addition, gaps_by_id)
    candidates: list[tuple[str | None, list[chess.Board]]] = []
    for parent_id, board in positions.items():
        if expected is not None:
            expected_number, expected_side = expected
            if board.fullmove_number != expected_number:
                continue
            if ("w" if board.turn else "b") != expected_side:
                continue
        played = _play_line(board, addition.moves)
        if played is not None:
            candidates.append((parent_id, played))
    if len(candidates) == 1:
        return candidates[0]
    hinted_parent = addition.parent_node_id
    if hinted_parent is not None:
        hinted_parent = hint_aliases.get(hinted_parent, hinted_parent)
        hinted = [candidate for candidate in candidates if candidate[0] == hinted_parent]
        if len(hinted) == 1:
            return hinted[0]
    preceding = [
        candidate
        for candidate in candidates
        if position_ranks[candidate[0]][0] <= insertion_position
    ]
    if preceding:
        closest_rank = max(position_ranks[candidate[0]] for candidate in preceding)
        closest = [
            candidate for candidate in preceding if position_ranks[candidate[0]] == closest_rank
        ]
        if len(closest) == 1:
            return closest[0]
    return None


def apply_ccef_coverage_supplement(
    original: StructuredGenerationResponse,
    supplement_response: StructuredGenerationResponse,
    context: CcefPromptContext,
    report: CcefCoverageReport,
    authority_package: ExtractionPackageV1_1,
) -> StructuredGenerationResponse:
    """Apply a supplement while resolving every parent with local chess rules."""

    if type(original) is not StructuredGenerationResponse:
        raise TypeError("original must be StructuredGenerationResponse")
    if type(supplement_response) is not StructuredGenerationResponse:
        raise TypeError("supplement_response must be StructuredGenerationResponse")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    if type(report) is not CcefCoverageReport:
        raise TypeError("report must be CcefCoverageReport")
    if type(authority_package) is not ExtractionPackageV1_1:
        raise TypeError("authority_package must be ExtractionPackageV1_1")
    try:
        original_package = ExtractionPackageV1_1.model_validate(_parse_payload(original))
        supplement = CcefCoverageSupplement.model_validate(_parse_payload(supplement_response))
    except (CcefDecodeError, ValidationError):
        raise CcefCoverageError(
            "invalid_supplement", "CCEF coverage supplement response is invalid"
        ) from None
    if supplement.base_response_sha256 != _response_sha256(original):
        raise CcefCoverageError(
            "binding_mismatch", "CCEF coverage supplement does not match its base"
        )
    gaps_by_id = {gap.gap_id: gap for gap in report.gaps}
    if set(supplement.resolves) != set(gaps_by_id):
        raise CcefCoverageError(
            "binding_mismatch", "CCEF coverage supplement must resolve every reported gap"
        )
    originals: dict[str, MoveSequenceItemV1_1] = {
        item.id: item for item in original_package.items if isinstance(item, MoveSequenceItemV1_1)
    }
    authorities: dict[str, MoveSequenceItemV1_1] = {
        item.id: item for item in authority_package.items if isinstance(item, MoveSequenceItemV1_1)
    }
    additions_by_sequence: dict[str, list[CcefCoverageAddition]] = {}
    added_count = sum(len(addition.moves) for addition in supplement.additions)
    if added_count > _MAX_ADDED_NODES:
        raise CcefCoverageError(
            "unauthorized_supplement", "CCEF coverage supplement has an invalid addition count"
        )
    for addition in supplement.additions:
        existing = originals.get(addition.sequence_id)
        if (
            existing is None
            or addition.sequence_id not in authorities
            or any(
                addition.sequence_id not in gaps_by_id[gap_id].candidate_sequence_ids
                for gap_id in addition.resolves
            )
        ):
            raise CcefCoverageError(
                "unauthorized_supplement", "CCEF coverage supplement chose an unrelated sequence"
            )
        existing_flow_ids = {_flow_identity(entry) for entry in existing.reading_flow}
        if (
            addition.insert_after_flow_id is not None
            and addition.insert_after_flow_id not in existing_flow_ids
        ):
            raise CcefCoverageError(
                "invalid_supplement", "CCEF coverage supplement insertion point does not exist"
            )
        additions_by_sequence.setdefault(addition.sequence_id, []).append(addition)

    replacements: dict[str, MoveSequenceItemV1_1] = {}
    for sequence_id, additions in additions_by_sequence.items():
        existing = originals[sequence_id]
        used_ids = {
            *[node.id for node in existing.nodes],
            *[annotation.id for annotation in existing.annotations],
        }
        child_counts: dict[str | None, int] = {}
        for node in existing.nodes:
            child_counts[node.parent_id] = child_counts.get(node.parent_id, 0) + 1
        flow_positions = {
            _flow_identity(entry): index for index, entry in enumerate(existing.reading_flow)
        }
        positions: dict[str | None, chess.Board] = {}
        position_ranks: dict[str | None, tuple[int, int]] = {}
        initial_board = _sequence_initial_board(authorities[sequence_id])
        if initial_board is not None:
            positions[None] = initial_board
            position_ranks[None] = (-1, 0)
        for node in authorities[sequence_id].nodes:
            if node.validation_status != "valid" or node.fen_after is None:
                continue
            try:
                positions[node.id] = chess.Board(node.fen_after, chess960=False)
                position_ranks[node.id] = (flow_positions[node.id], 0)
            except ValueError:
                continue

        generated_by_position: dict[int, list[MoveNode]] = {}
        generated_anchor_positions: dict[str, int] = {}
        hint_aliases: dict[str, str] = {}
        remaining = list(additions)
        generated_serial = 0
        while remaining:
            progress = False
            for addition in list(remaining):
                requested_position = (
                    -1
                    if addition.insert_after_flow_id is None
                    else flow_positions[addition.insert_after_flow_id]
                )
                resolved = _candidate_parent(
                    addition,
                    gaps_by_id,
                    positions,
                    position_ranks,
                    requested_position,
                    hint_aliases,
                )
                if resolved is None:
                    continue
                parent_id, after_positions = resolved
                if parent_id in flow_positions:
                    requested_position = max(requested_position, flow_positions[parent_id])
                elif parent_id is not None:
                    requested_position = max(
                        requested_position, generated_anchor_positions[parent_id]
                    )

                evidence: list[EvidenceRef] = []
                seen_evidence: set[tuple[int, str]] = set()
                for gap_id in addition.resolves:
                    for source in gaps_by_id[gap_id].trusted_evidence:
                        key = (source.physical_page, source.fragment_sha256)
                        if key not in seen_evidence:
                            seen_evidence.add(key)
                            evidence.append(EvidenceRef(page=key[0], fragment_sha256=key[1]))
                generated: list[MoveNode] = []
                for move_index, (move_text, after_board) in enumerate(
                    zip(addition.moves, after_positions, strict=True)
                ):
                    node_id = _generated_node_id(
                        supplement.base_response_sha256,
                        addition.addition_id,
                        move_index,
                        used_ids,
                    )
                    sibling_order = child_counts.get(parent_id, 0)
                    child_counts[parent_id] = sibling_order + 1
                    node = MoveNode(
                        id=node_id,
                        parent_id=parent_id,
                        sibling_order=sibling_order,
                        move_text=move_text,
                        evidence=copy.deepcopy(evidence),
                    )
                    generated.append(node)
                    positions[node_id] = after_board
                    generated_serial += 1
                    position_ranks[node_id] = (requested_position, generated_serial)
                    generated_anchor_positions[node_id] = requested_position
                    hint_aliases[f"{addition.addition_id}-node{move_index + 1}"] = node_id
                    parent_id = node_id
                generated_by_position.setdefault(requested_position, []).extend(generated)
                remaining.remove(addition)
                progress = True
            if not progress:
                raise CcefCoverageError(
                    "invalid_supplement",
                    "CCEF coverage supplement cannot be attached to a unique legal position",
                )

        final_flow: list[MoveFlowRef | AnnotationFlowRef] = []
        for node in generated_by_position.get(-1, []):
            final_flow.append(MoveFlowRef(kind="move", node_id=node.id))
        for flow_position, entry in enumerate(existing.reading_flow):
            final_flow.append(copy.deepcopy(entry))
            for node in generated_by_position.get(flow_position, []):
                final_flow.append(MoveFlowRef(kind="move", node_id=node.id))
        nodes_by_id = {node.id: copy.deepcopy(node) for node in existing.nodes}
        for generated in generated_by_position.values():
            nodes_by_id.update((node.id, node) for node in generated)
        final_nodes = [
            nodes_by_id[entry.node_id] for entry in final_flow if isinstance(entry, MoveFlowRef)
        ]
        replacements[sequence_id] = existing.model_copy(
            update={"nodes": final_nodes, "reading_flow": final_flow}, deep=True
        )

    updated_items = [replacements.get(item.id, item) for item in original_package.items]
    try:
        updated = ExtractionPackageV1_1.model_validate(
            original_package.model_copy(update={"items": updated_items}).model_dump(mode="json")
        )
    except ValidationError:
        raise CcefCoverageError(
            "invalid_supplement", "CCEF coverage supplement breaks package structure"
        ) from None
    return original.model_copy(update={"content": _canonical_json(updated.model_dump(mode="json"))})


def ccef_coverage_chain_document(
    base_document: object,
    supplemented: StructuredGenerationResponse,
    supplement_response: StructuredGenerationResponse,
    report: CcefCoverageReport,
) -> dict[str, object]:
    return {
        "artifact_schema": "chess-workbench/ccef-coverage-chain/1.0",
        "base_generation": copy.deepcopy(base_document),
        "coverage_gaps": [
            {
                "gap_id": gap.gap_id,
                "physical_page": gap.physical_page,
                "moves": [move.model_dump(mode="json") for move in gap.moves],
            }
            for gap in report.gaps
        ],
        "supplement_response": supplement_response.model_dump(mode="json"),
        "supplemented_content_sha256": _response_sha256(supplemented),
    }


__all__ = [
    "CCEF_COVERAGE_SUPPLEMENT_SCHEMA",
    "CcefCoverageError",
    "CcefCoverageGap",
    "CcefCoverageReport",
    "CcefCoverageSupplement",
    "apply_ccef_coverage_supplement",
    "build_ccef_coverage_supplement_request",
    "ccef_coverage_chain_document",
    "inspect_ccef_move_coverage",
]
