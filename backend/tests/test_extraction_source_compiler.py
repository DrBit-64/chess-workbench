"""Focused source-bound compilation regression: nested branches and local damage."""

import json
import re
from datetime import UTC, datetime
from uuid import UUID

from chess_workbench.extraction.contracts import MoveSequenceItemV1_1, UnresolvedItem
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.interpretation import resolve_semantic_response
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.source_compiler import compile_semantic_events


def _context(source: str) -> CcefPromptContext:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=source,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, source, "embedded_text", "test", "1"),
    )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000001"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        ],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    return context


def test_source_suffix_becomes_structured_nag_without_changing_source_move() -> None:
    source = "1 e4! e5?"
    context = _context(source)
    events = [
        {
            "id": event_id,
            "kind": "move",
            "sequence": "game",
            "parent": parent,
            "source": {
                "page": 1,
                "order": 0,
                "start": source.index(token),
                "end": source.index(token) + len(token),
            },
        }
        for event_id, token, parent in [
            ("white", "e4!", None),
            ("black", "e5?", "white"),
        ]
    ]

    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [(node.move_text, node.san_candidate, node.nags) for node in sequence.nodes] == [
        ("e4!", "e4", [1]),
        ("e5?", "e5", [2]),
    ]


def test_nested_variation_resumes_mainline_after_bad_event() -> None:
    source = "e4 e5 c5 Nf3 d6 Nc6 d4 bad Nf3 Main line"
    context = _context(source)
    specs = [
        ("a", "e4", None),
        ("b", "e5", "a"),
        ("c", "c5", "a"),
        ("d", "Nf3", "c"),
        ("e", "d6", "d"),
        ("f", "Nc6", "d"),
        ("g", "d4", "e"),
        ("bad", "bad", "missing"),
        ("h", "Nf3", "b"),
    ]
    events = []
    cursor = 0
    for event_id, token, parent in specs:
        start = source.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    events.append(
        {
            "id": "note",
            "kind": "annotation",
            "sequence": "game",
            "anchor": "h",
            "source": {
                "page": 1,
                "order": 0,
                "start": source.index("Main line"),
                "end": len(source),
            },
        }
    )
    quoted = []
    for event in events:
        clone = event.copy()
        location = clone["source"]
        quote = source[location["start"] : location["end"]]
        clone["source"] = {
            "page": 1,
            "order": 0,
            "quote": quote,
            "occurrence": source[: location["start"]].count(quote),
        }
        if event["id"] == "f":
            clone["mainline"] = True
        quoted.append(clone)
    quoted.insert(
        8,
        {
            "id": "missing_quote",
            "kind": "move",
            "sequence": "game",
            "parent": "e",
            "source": {"page": 1, "order": 0, "quote": "impossible token"},
        },
    )
    resolved = resolve_semantic_response(context, json.dumps({"events": quoted}))
    result = compile_semantic_events(context, resolved)
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.move_text for node in sequence.nodes] == [
        "e4",
        "e5",
        "c5",
        "Nf3",
        "d6",
        "Nc6",
        "d4",
        "Nf3",
    ]
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert [node.sibling_order for node in sequence.nodes if node.parent_id == "move4"] == [1, 0]
    assert sequence.annotations[0].anchor.node_id == sequence.nodes[-1].id
    assert [entry.kind for entry in sequence.reading_flow][-1] == "annotation"
    unresolved = [item for item in result.items if isinstance(item, UnresolvedItem)]
    assert len(unresolved) == 2
    assert {item.reason_code for item in unresolved} == {
        "semantic_event_invalid",
        "source_quote_missing",
    }
    assert result.diagnostics[0].code == "semantic_event_invalid"


def test_numbered_variation_relinks_to_unique_legal_ancestor() -> None:
    source = "1 e4 d5 2 exd5 Nf6 3 d4 Bg4 via 3 Nf3 Bg4 4 d4"
    context = _context(source)
    specs = [
        ("m1", "e4", None, "game"),
        ("m2", "d5", "m1", "game"),
        ("m3", "exd5", "m2", "game"),
        ("m4", "Nf6", "m3", "game"),
        ("m5", "d4", "m4", "game"),
        ("m6", "Bg4", "m5", "game"),
        # The model incorrectly used m6 and called the branch a new sequence.
        ("a1", "Nf3", "m6", "alternative"),
        ("a2", "Bg4", "a1", "alternative"),
        ("a3", "d4", "a2", "alternative"),
    ]
    events = []
    cursor = 0
    for event_id, token, parent, sequence in specs:
        start = source.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": sequence,
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    result = compile_semantic_events(context, events)
    sequences = [item for item in result.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(sequences) == 1
    assert [node.validation_status for node in sequences[0].nodes] == ["valid"] * 9
    assert sequences[0].nodes[6].parent_id == sequences[0].nodes[3].id
    assert sequences[0].nodes[6].sibling_order == 1
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "sequence_alias_corrected",
        "source_parent_relinked",
    }


def test_numbered_nested_alternatives_use_the_stated_shared_predecessor() -> None:
    # Scandinavian, physical pp. 321-322: the printed 7 c4 and nested
    # 7 Nc3 are alternatives to the game's 7 O-O, not continuations of it.
    source = (
        "1 e4 d5 2 exd5 Nf6 3 d4 Bg4 4 Nf3 Qxd5 5 Be2 Nc6 "
        "6 Be3 O-O-O 7 O-O After 7 c4 (7 Nc3?! Qf5!)"
    )
    context = _context(source)
    specs = [
        ("e4", "e4", None),
        ("d5", "d5", "e4"),
        ("exd5", "exd5", "d5"),
        ("Nf6", "Nf6", "exd5"),
        ("d4", "d4", "Nf6"),
        ("Bg4", "Bg4", "d4"),
        ("Nf3", "Nf3", "Bg4"),
        ("Qxd5", "Qxd5", "Nf3"),
        ("Be2", "Be2", "Qxd5"),
        ("Nc6", "Nc6", "Be2"),
        ("Be3", "Be3", "Nc6"),
        ("castle_black", "O-O-O", "Be3"),
        ("castle_white", "O-O", "castle_black"),
        ("c4", "c4", "castle_white"),
        ("Nc3", "Nc3", "c4"),
        ("Qf5", "Qf5", "Nc3"),
    ]
    events = []
    cursor = 0
    for event_id, quote, parent in specs:
        start = source.index(quote, cursor)
        cursor = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    nodes = {node.move_text: node for node in sequence.nodes}
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert nodes["c4"].parent_id == nodes["O-O-O"].id
    assert nodes["Nc3"].parent_id == nodes["O-O-O"].id
    assert nodes["Qf5"].parent_id == nodes["Nc3"].id


def test_later_black_first_reply_resumes_unique_open_game_root() -> None:
    # Catalan, physical p6: a complete illustrative move order is printed
    # between the game's standalone 1.d4 and its standalone 1...d5 reply.
    source = "1 d4 | 1 d4 Nf6 | 1... d5 2 c4"
    context = _context(source)
    specs = [
        ("game_first", "d4", None, "game"),
        ("example_first", "d4", None, "example"),
        ("example_reply", "Nf6", "example_first", "example"),
        ("game_reply", "d5", None, "resumed"),
        ("game_second", "c4", "game_reply", "resumed"),
    ]
    events = []
    cursor = 0
    for event_id, quote, parent, sequence in specs:
        start = source.index(quote, cursor)
        cursor = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": sequence,
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    package = compile_semantic_events(context, events)
    sequences = [item for item in package.items if isinstance(item, MoveSequenceItemV1_1)]
    assert [[node.move_text for node in item.nodes] for item in sequences] == [
        ["d4", "d5", "c4"],
        ["d4", "Nf6"],
    ]
    assert all(node.validation_status == "valid" for item in sequences for node in item.nodes)
    assert any(d.code == "source_root_continuation" for d in package.diagnostics)


def test_numbered_successor_disambiguates_catalan_branch_parent() -> None:
    # Catalan p6 prints 3.g3 as an alternative, then resumes the game's
    # 3.Nf3 line with 3...Nf6 4.g3. Nf6 alone is legal in both branches.
    source = "1 d4 d5 2 c4 e6 3 Nf3 3 g3 3...Nf6 4 g3 4...Be7"
    context = _context(source)
    specs = [
        ("d4", "d4", None),
        ("d5", "d5", "d4"),
        ("c4", "c4", "d5"),
        ("e6", "e6", "c4"),
        ("Nf3", "Nf3", "e6"),
        ("alternative", "g3", "Nf3"),
        ("Nf6", "Nf6", "alternative"),
        ("main_g3", "g3", "Nf6"),
        ("Be7", "Be7", "main_g3"),
    ]
    events = []
    cursor = 0
    for event_id, quote, parent in specs:
        start = source.index(quote, cursor)
        cursor = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    by_text = {node.move_text: node for node in sequence.nodes if node.move_text != "g3"}
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert by_text["Nf6"].parent_id == by_text["Nf3"].id
    assert sum(d.code == "source_parent_relinked" for d in package.diagnostics) == 2


def test_question_options_keep_one_played_move_and_later_game_needs_seed() -> None:
    lines = [
        "choice: 9...dxe4, 9...Na6",
        "and 9...Nbd7?",
        "9...Nbd7?!",
        "The game move 9...Nbd7 was played.",
        "16...Nb6 17 b3!",
    ]
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=index,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=line,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, line, "embedded_text", "test", "1"),
            ),
        )
        for index, line in enumerate(lines)
    ]
    context = _context("placeholder").model_copy(
        update={"pages": [PromptEvidencePage(physical_page=1, fragments=entries)]}
    )
    specs = [
        ("option1", 0, "9...dxe4", "choice", None),
        ("option2", 0, "9...Na6", "choice", None),
        ("question", 1, "9...Nbd7", "choice", None),
        ("played", 2, "9...Nbd7?!", "choice", None),
        ("later", 4, "16...Nb6", "later_game", None),
        ("reply", 4, "17 b3!", "later_game", "later"),
    ]
    events = []
    for event_id, order, token, sequence, parent in specs:
        start = lines[order].index(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": sequence,
                "parent": parent,
                "source": {"page": 1, "order": order, "start": start, "end": start + len(token)},
            }
        )
    result = compile_semantic_events(
        context,
        events,
        sequence_initial_fens={
            "choice": "rn1q1rk1/pb2bppp/1pp1pn2/3p4/2PPP3/5NP1/PPQN1PBP/R1B2RK1 b - e3 0 9"
        },
    )
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 3
    assert [node.move_text for node in sequence.nodes] == ["9...dxe4", "9...Na6", "9...Nbd7?!"]
    assert sequence.nodes[-1].sibling_order == 0
    assert len(sequence.nodes[-1].evidence) == 2
    assert {item.reason_code for item in result.items if isinstance(item, UnresolvedItem)} == {
        "missing_initial_position",
        "semantic_event_invalid",
    }


def test_diagram_seed_starts_midgame_without_model_fen() -> None:
    fen = "r7/2p5/1p2pR2/2p1P3/2P3k1/1P6/6K1/8 w - - 0 36"
    marker = json.dumps(
        {
            "kind": "chess_diagram",
            "operational_fen": fen,
            "next_formal_move": {"move_number": 36, "side_to_move": "w"},
        }
    )
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    pages = []
    for page, text, origin in [
        (1, marker, "diagram"),
        (2, "36.Rxe6? 36.Kf2!", "embedded_text"),
    ]:
        fragment = SourceEvidenceFragment(
            physical_page=page,
            box=box,
            text=text,
            origin=origin,
            confidence=0.9 if origin == "diagram" else None,
            engine_name="test",
            engine_version="1",
            fragment_sha256=source_fragment_sha256(page, box, text, origin, "test", "1"),
        )
        pages.append(
            PromptEvidencePage(
                physical_page=page,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        )
    context = _context("placeholder").model_copy(
        update={"first_page": 1, "last_page": 2, "pages": pages}
    )
    events = []
    for event_id, token in (("main", "36.Rxe6?"), ("alternative", "36.Kf2!")):
        start = pages[1].fragments[0].fragment.text.index(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "source": {"page": 2, "order": 0, "start": start, "end": start + len(token)},
            }
        )
    result = compile_semantic_events(context, events)
    assert [item.kind for item in result.items] == ["figure", "move_sequence"]
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert sequence.initial_position.fen == fen
    assert [node.validation_status for node in sequence.nodes] == ["valid", "valid"]


def test_repeated_endgame_move_uses_the_numbered_source_occurrence() -> None:
    # Endgame Strategy, physical p21: the model's second Bg7 quote selected
    # the printed 57th move, skipping the first Bg7 inside this same line.
    source = "53.Bg7 Rdd6 54.Bc3 Rd3 55.Bg7 Rdd6 56.Bc3 Rd3 57.Bg7"
    context = _context(source)
    specs = [
        ("a", "Bg7", 0, None),
        ("b", "Rdd6", 0, "a"),
        ("c", "Bc3", 0, "b"),
        ("d", "Rd3", 0, "c"),
        ("e", "Bg7", 2, "d"),  # Incorrect model occurrence; 55.Bg7 is index 1.
        ("f", "Rdd6", 1, "e"),
        ("g", "Bc3", 1, "f"),
        ("h", "Rd3", 1, "g"),
    ]
    events = []
    for event_id, quote, occurrence, parent in specs:
        starts = [match.start() for match in re.finditer(quote, source)]
        start = starts[occurrence]
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": start + len(quote)},
            }
        )
    result = compile_semantic_events(
        context,
        events,
        sequence_initial_fens={"game": "6k1/p3R3/2r4p/6pN/2p5/2BrP1P1/P4K1P/8 w - - 0 53"},
    )
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert sequence.nodes[4].move_number == 55
    assert sequence.nodes[4].evidence[0].start_offset == source.index("55.Bg7") + 3
    assert any(diagnostic.code == "source_occurrence_rebound" for diagnostic in result.diagnostics)


def test_repeated_move_page_count_resolves_within_its_fragment() -> None:
    first = "53.Bg7"
    second = "54.Bc3 Rd3 55.Bg7 Rdd6 56.Bc3 Rd3 57.Bg7"
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=text,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "test", "1"),
            ),
        )
        for order, text in enumerate((first, second))
    ]
    context = _context("placeholder").model_copy(
        update={"pages": [PromptEvidencePage(physical_page=1, fragments=entries)]}
    )
    resolved = resolve_semantic_response(
        context,
        json.dumps(
            {
                "events": [
                    {
                        "id": "last",
                        "kind": "move",
                        "source": {"page": 1, "order": 1, "quote": "Bg7", "occurrence": 2},
                    }
                ]
            }
        ),
    )
    assert resolved[0]["source"]["start"] == second.index("57.Bg7") + 3


def test_two_dependent_wrong_parents_relink_from_diagram_seed() -> None:
    source = "36.Rxe6? 36.Kf2! Ra3 37.Ke3 Rxb3+ 38.Kd2 38.Ke4 38...Rc3"
    context = _context(source)
    specs = [
        ("main", "36.Rxe6?", None),
        ("better", "36.Kf2!", "main"),
        ("reply", "Ra3", "better"),
        ("next", "37.Ke3", "reply"),
        ("capture", "Rxb3+", "next"),
        ("quiet", "38.Kd2", "capture"),
        ("active", "38.Ke4", "quiet"),
        ("example", "38...Rc3", "active"),
    ]
    events = []
    cursor = 0
    for event_id, token, parent in specs:
        start = source.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    result = compile_semantic_events(
        context,
        events,
        sequence_initial_fens={"game": "r7/2p5/1p2pR2/2p1P3/2P3k1/1P6/6K1/8 w - - 0 36"},
    )
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.validation_status for node in sequence.nodes] == ["valid"] * 8
    assert sequence.nodes[1].parent_id is None
    assert sequence.nodes[6].parent_id == sequence.nodes[4].id
    assert [diagnostic.code for diagnostic in result.diagnostics].count(
        "source_parent_relinked"
    ) == 2


def test_confirmed_same_position_joins_root_alternatives_from_model_sequences() -> None:
    source = "6...c6 6...c5 7.d5"
    context = _context(source)
    fen = "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2N2N1P/PP3PP1/R1BQKB1R b KQ - 0 6"
    specs = [
        ("main", "6...c6", "line1", None),
        ("alternative", "6...c5", "line2", None),
        ("continuation", "7.d5", "line2", "alternative"),
    ]
    events = []
    cursor = 0
    for event_id, token, sequence, parent in specs:
        start = source.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": sequence,
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    result = compile_semantic_events(
        context, events, sequence_initial_fens={"line1": fen, "line2": fen}
    )
    sequences = [item for item in result.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(sequences) == 1
    assert [node.validation_status for node in sequences[0].nodes] == ["valid"] * 3
    assert [node.parent_id for node in sequences[0].nodes] == [None, None, "move2"]
    assert [node.sibling_order for node in sequences[0].nodes[:2]] == [0, 1]
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"root_alternative_joined"}


def test_castling_zero_is_not_a_printed_move_number() -> None:
    from chess_workbench.extraction.source_compiler import _printed_move_context

    assert _printed_move_context("6 ... 0-0-0", 6, "0-0-0") == (6, "b")
    assert _printed_move_context("0-0-0 Nc2!", 6, "Nc2!") == (None, None)


def test_unique_exact_quote_recovers_shifted_fragment_order_only_on_same_page() -> None:
    context = _context("First paragraph.")
    first = context.pages[0].fragments[0]
    text = "Second paragraph with Nc6."
    box = first.fragment.box
    second_fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=text,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "test", "1"),
    )
    page = PromptEvidencePage(
        physical_page=1,
        fragments=[first, PromptEvidenceFragment(order=1, fragment=second_fragment)],
    )
    context = CcefPromptContext.model_validate(
        context.model_copy(update={"pages": [page]}).model_dump(mode="python")
    )
    events = resolve_semantic_response(
        context,
        json.dumps(
            {
                "events": [
                    {
                        "id": "p",
                        "kind": "prose",
                        "source": {"page": 1, "order": 0, "quote": "Second paragraph with Nc6."},
                    }
                ]
            }
        ),
    )
    assert events[0]["kind"] == "prose"
    assert events[0]["source"] == {"page": 1, "order": 1, "start": 0, "end": len(text)}


def test_reply_after_intervening_sibling_resumes_printed_mainline() -> None:
    # Catalan p6: 6.O-O is followed by the sibling choices 6.Nbd2 and
    # 6.Qc2 before the separate 6...c6 line resumes the played score.
    source = "1 d4 d5 2 c4 e6 3 Nf3 Nf6 4 g3 Be7 5 Bg2 O-O 6 O-O 6 Nbd2 6 Qc2 6... c6"
    context = _context(source)
    specs = [
        ("d4", "d4", None),
        ("d5", "d5", "d4"),
        ("c4", "c4", "d5"),
        ("e6", "e6", "c4"),
        ("Nf3", "Nf3", "e6"),
        ("Nf6", "Nf6", "Nf3"),
        ("g3", "g3", "Nf6"),
        ("Be7", "Be7", "g3"),
        ("Bg2", "Bg2", "Be7"),
        ("black_castle", "O-O", "Bg2"),
        ("white_castle", "O-O", "black_castle"),
        ("Nbd2", "Nbd2", "black_castle"),
        ("Qc2", "Qc2", "black_castle"),
        ("c6", "c6", "Nbd2"),
    ]
    events = []
    cursor = 0
    for event_id, quote, parent in specs:
        start = source.index(quote, cursor)
        cursor = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": cursor},
            }
        )
    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    nodes = {event["id"]: node for event, node in zip(events, sequence.nodes, strict=True)}
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert nodes["c6"].parent_id == nodes["white_castle"].id
    assert any(
        diagnostic.code == "source_parent_relinked" and diagnostic.node_id == nodes["c6"].id
        for diagnostic in package.diagnostics
    )


def test_reprinted_move_before_reply_remains_readable_once() -> None:
    # Endgame p20 resumes a line by printing 36.Rxe6? a second time.
    lines = ("36.Rxe6?", "36.Rxe6? Kf5!")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=line,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, line, "embedded_text", "test", "1"),
            ),
        )
        for order, line in enumerate(lines)
    ]
    context = _context("placeholder").model_copy(
        update={"pages": [PromptEvidencePage(physical_page=1, fragments=entries)]}
    )
    events = [
        {
            "id": "first",
            "kind": "move",
            "sequence": "game",
            "source": {"page": 1, "order": 0, "start": 3, "end": 8},
        },
        {
            "id": "reply",
            "kind": "move",
            "sequence": "game",
            "parent": "first",
            "source": {"page": 1, "order": 1, "start": 9, "end": 13},
        },
    ]
    result = compile_semantic_events(
        context,
        events,
        sequence_initial_fens={"game": "r7/2p5/1p2pR2/2p1P3/2P3k1/1P6/6K1/8 w - - 0 36"},
    )
    sequence = next(item for item in result.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.validation_status for node in sequence.nodes] == ["valid", "valid"]
    assert [(a.text, a.evidence[0].start_offset) for a in sequence.annotations] == [("36.Rxe6?", 0)]
    assert [entry.kind for entry in sequence.reading_flow] == [
        "move",
        "annotation",
        "move",
    ]


def test_annotation_infers_sequence_from_verified_move_anchor() -> None:
    source = "1 e4 The move controls the centre."
    context = _context(source)
    events = [
        {
            "id": "played",
            "kind": "move",
            "sequence": "game",
            "source": {"page": 1, "order": 0, "start": 2, "end": 4},
        },
        {
            "id": "explanation",
            "kind": "annotation",
            "anchor": "played",
            "source": {
                "page": 1,
                "order": 0,
                "start": source.index("The move"),
                "end": len(source),
            },
        },
    ]
    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.annotations) == 1
    assert sequence.annotations[0].text == "The move controls the centre."
    assert sequence.annotations[0].anchor.node_id == sequence.nodes[0].id
    assert not any(isinstance(item, UnresolvedItem) for item in package.items)


def test_colored_example_end_resumes_unique_legal_mainline() -> None:
    lines = (
        ("1 e4 e5 2 Nf3 Nc6 3 Bb5 a6", "#000000"),
        ("3 Bc4 Nf6 4 d3 Be7", "#000080"),
        ("4 d3", "#000000"),
    )
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=line,
                origin="embedded_text",
                font_color=color,
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, line, "embedded_text", "test", "1"),
            ),
        )
        for order, (line, color) in enumerate(lines)
    ]
    context = _context("placeholder").model_copy(
        update={"pages": [PromptEvidencePage(physical_page=1, fragments=entries)]}
    )
    specs = [
        ("e4", 0, "e4", None),
        ("e5", 0, "e5", "e4"),
        ("nf3", 0, "Nf3", "e5"),
        ("nc6", 0, "Nc6", "nf3"),
        ("bb5", 0, "Bb5", "nc6"),
        ("a6", 0, "a6", "bb5"),
        ("bc4", 1, "Bc4", "nc6"),
        ("nf6", 1, "Nf6", "bc4"),
        ("blue_d3", 1, "d3", "nf6"),
        ("be7", 1, "Be7", "blue_d3"),
        ("black_d3", 2, "d3", "be7"),
    ]
    events = []
    cursors = [0, 0, 0]
    for event_id, order, quote, parent in specs:
        start = lines[order][0].index(quote, cursors[order])
        cursors[order] = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "mainline": order != 1,
                "source": {"page": 1, "order": order, "start": start, "end": cursors[order]},
            }
        )
    package = compile_semantic_events(context, events)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    nodes = {event["id"]: node for event, node in zip(events, sequence.nodes, strict=True)}
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert nodes["black_d3"].parent_id == nodes["a6"].id
    assert any(w.code == "source_parent_relinked" for w in nodes["black_d3"].warnings)

    # A same-color but too-early parent is resolved by the nearest preceding
    # legal position, rather than the blue example's equally legal position.
    events[-1]["parent"] = "bb5"
    nearest = compile_semantic_events(context, events)
    nearest_sequence = next(
        item for item in nearest.items if isinstance(item, MoveSequenceItemV1_1)
    )
    nearest_nodes = {
        event["id"]: node for event, node in zip(events, nearest_sequence.nodes, strict=True)
    }
    assert nearest_nodes["black_d3"].validation_status == "valid"
    assert nearest_nodes["black_d3"].parent_id == nearest_nodes["a6"].id


def test_spaced_black_ellipsis_keeps_printed_turn() -> None:
    from chess_workbench.extraction.source_compiler import _printed_move_context

    assert _printed_move_context("7 ... Qh5!", 0, "7 ... Qh5!") == (7, "b")


def test_parenthesized_choice_keeps_outer_reply_and_formal_line_resumes_mainline() -> None:
    lines = (
        "6...O-O-O",
        "7 O-O",
        "After 7 c4 (7 Nc3 Qf5) 7...Qf5",
        "7...Qf5 8 Nbd2",
    )
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=line,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, line, "embedded_text", "test", "1"),
            ),
        )
        for order, line in enumerate(lines)
    ]
    context = _context("placeholder").model_copy(
        update={"pages": [PromptEvidencePage(physical_page=1, fragments=entries)]}
    )
    specs = [
        ("castle", 0, "6...O-O-O", None, True),
        ("played", 1, "7 O-O", "castle", True),
        ("c4", 2, "c4", "castle", False),
        ("nc3", 2, "Nc3", "c4", False),
        ("inner", 2, "Qf5", "nc3", False),
        ("outer", 2, "Qf5", "c4", False),
        ("formal", 3, "Qf5", "c4", True),
        ("nbd2", 3, "Nbd2", "formal", True),
    ]
    cursors = [0] * len(lines)
    events = []
    for event_id, order, quote, parent, mainline in specs:
        start = lines[order].index(quote, cursors[order])
        cursors[order] = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "mainline": mainline,
                "source": {"page": 1, "order": order, "start": start, "end": cursors[order]},
            }
        )
    fen = "r3kb1r/ppp1pppp/2n2n2/3q4/3P2b1/4BN2/PPP1BPPP/RN1QK2R b KQkq - 3 6"
    package = compile_semantic_events(context, events, sequence_initial_fens={"game": fen})
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    nodes = {event["id"]: node for event, node in zip(events, sequence.nodes, strict=True)}
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert nodes["outer"].parent_id == nodes["c4"].id
    assert nodes["formal"].parent_id == nodes["played"].id
    assert nodes["nbd2"].parent_id == nodes["formal"].id
