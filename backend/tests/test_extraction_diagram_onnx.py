"""Rendered-page board geometry, including vector-style page borders."""

import numpy as np

from chess_workbench.extraction.diagram_onnx import _page_border_candidates


def test_non_square_vector_board_frame_is_found_on_full_text_page() -> None:
    page = np.full((1100, 850), 255, dtype=np.float32)
    x0, x1, y0, y1 = 220, 510, 300, 601
    for rank in range(8):
        for file in range(8):
            if (rank + file) % 2:
                a = x0 + round(file * (x1 - x0) / 8)
                b = x0 + round((file + 1) * (x1 - x0) / 8)
                c = y0 + round(rank * (y1 - y0) / 8)
                d = y0 + round((rank + 1) * (y1 - y0) / 8)
                page[c:d, a:b] = 210
    page[y0, x0:x1] = 40
    page[y1, x0:x1] = 40
    candidates = _page_border_candidates(page)
    assert any(
        abs(box.x0 - x0) <= 2
        and abs(box.x1 - x1) <= 3
        and abs(box.y0 - y0) <= 2
        and abs(box.y1 - y1) <= 2
        for box in candidates
    )
