from __future__ import annotations

import json

from chess_workbench.extraction.diagram import ChessDiagramRecognition
from chess_workbench.extraction.diagram_context import (
    DiagramEvidencePage,
    resolve_diagram_evidence,
)
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    PixelBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)


def _text_fragment(text: str, *, y0: float = 0.7, y1: float = 0.8) -> SourceEvidenceFragment:
    box = NormalizedBox(x0=0.1, y0=y0, x1=0.9, y1=y1)
    digest = source_fragment_sha256(1, box, text, "embedded_text", "test", "1")
    return SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=text,
        origin="embedded_text",
        confidence=None,
        engine_name="test",
        engine_version="1",
        fragment_sha256=digest,
    )


def test_recognized_diagram_joins_the_shared_evidence_stream_with_legal_fen() -> None:
    recognition = ChessDiagramRecognition(
        physical_page=1,
        page_box=PixelBox(x0=100, y0=100, x1=500, y1=500),
        image_sha256="a" * 64,
        piece_placement="4k3/8/8/8/8/8/4P3/4K3",
        orientation="white",
        mean_confidence=0.9,
        min_confidence=0.9,
        square_confidences=[0.9] * 64,
        engine_name="local-test",
        engine_version="1",
    )
    resolved = resolve_diagram_evidence(
        [
            DiagramEvidencePage(
                physical_page=1,
                width=1000,
                height=1000,
                fragments=[_text_fragment("1.e4 begins the score")],
                recognitions=[recognition],
            )
        ]
    )[0]

    assert [fragment.origin for fragment in resolved.fragments] == [
        "diagram",
        "embedded_text",
    ]
    marker = json.loads(resolved.fragments[0].text)
    assert marker["operational_fen"] == "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    assert marker["next_formal_move"] == {
        "move_number": 1,
        "side_to_move": "w",
        "source_token": "e4",
    }
    assert resolved.diagram_count == 1
    assert resolved.unresolved_diagram_count == 0


def test_page_without_diagram_keeps_ordinary_evidence_unchanged() -> None:
    fragment = _text_fragment("Ordinary prose without a chessboard image")

    resolved = resolve_diagram_evidence(
        [
            DiagramEvidencePage(
                physical_page=1,
                width=1000,
                height=1000,
                fragments=[fragment],
            )
        ]
    )[0]

    assert resolved.fragments == [fragment]
    assert resolved.diagram_count == 0
    assert resolved.unresolved_diagram_count == 0


def test_explicit_side_caption_filters_conflicting_prose_move_context() -> None:
    recognition = ChessDiagramRecognition(
        physical_page=1,
        page_box=PixelBox(x0=100, y0=100, x1=500, y1=500),
        image_sha256="b" * 64,
        piece_placement="8/4kp2/5p2/4p1b1/1R6/6P1/3nKP1P/8",
        orientation="white",
        mean_confidence=0.9,
        min_confidence=0.9,
        square_confidences=[0.9] * 64,
        engine_name="local-test",
        engine_version="1",
    )
    resolved = resolve_diagram_evidence(
        [
            DiagramEvidencePage(
                physical_page=1,
                width=1000,
                height=1000,
                fragments=[
                    _text_fragment("Black to move", y0=0.51, y1=0.54),
                    _text_fragment(
                        "The threat is 33.f4, but the game continued 32...e4?",
                        y0=0.55,
                        y1=0.62,
                    ),
                ],
                recognitions=[recognition],
            )
        ]
    )[0]

    marker = json.loads(resolved.fragments[0].text)
    assert marker["operational_fen"] == ("8/4kp2/5p2/4p1b1/1R6/6P1/3nKP1P/8 b - - 0 32")
    assert marker["next_formal_move"] == {
        "move_number": 32,
        "side_to_move": "b",
        "source_token": "e4?",
    }
