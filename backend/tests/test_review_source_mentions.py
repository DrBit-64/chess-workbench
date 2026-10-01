"""Source notation for the review UI must separate plans from square names."""

from test_extraction_relations import _context

from chess_workbench.review.source_mentions import source_move_mentions


def test_whole_coordinate_moves_and_square_references_across_source_lines() -> None:
    context = _context("17 ... Qc8! threatens a sacrifice on")
    next_line = _context("h3. The plan is h7-h6, a7-a6 or Ne7; the outpost on d4.")
    entry = next_line.pages[0].fragments[0].model_copy(update={"order": 1})
    context.pages[0].fragments.append(entry)
    mentions = source_move_mentions(context)
    text = entry.fragment.text
    assert [(text[m["start"] : m["end"]], m["kind"]) for m in mentions[(1, 1)]] == [
        ("h3", "square"),
        ("h7-h6", "candidate"),
        ("a7-a6", "candidate"),
        ("Ne7", "candidate"),
        ("d4", "square"),
    ]
    assert len(mentions[(1, 0)]) == 1
