# PDF extraction P0: two local development windows

Date: 2026-09-24. Physical PDF pages are 1-based. This is a minimal manual oracle, not a fully
transcribed gold set. The local read-only census is reproducible with
`backend/.venv/bin/python scripts/evaluate_pdf_extraction.py`; full run IDs, content hashes and
counts are written to ignored `data/debug/extraction-audit-20260924/p0-baseline.json`.
The script does not contact a provider or update SQL.

| Window | Historical outcome | Required observations for the next slice |
| --- | --- | --- |
| Catalan p6–9 | Four historical runs all failed; no committed normalized candidate for this exact range. | Preserve double-column question/answer text; treat `9...dxe4` and `9...Na6` as alternatives from the same parent; retain `17...Nc4` and `18...Nxe3` as an incomplete plan, not a forced playable line. Existing saved model response already contained the p7 alternatives as sibling nodes, but failed later. |
| Scandinavian p319–323 | Thirteen historical runs: five succeeded, five failed and three cancelled across different versions. The last successful normalized candidate has two move sequences, 120 nodes, seven sequence annotations and no unresolved items. | Recognize undotted numbered score such as `1 e4 d5`, preserve the chapter introduction and cross-page game, keep printed variations attached to their actual parent. Do not treat the historical success/counts as a gold quality label. |

P1 success requires one locally compiled CCEF 1.1 candidate containing a source-bound mainline, a
true variation with correct parent, at least one intact source annotation and source reading order.
A scripted semantic proposal is acceptable first; real provider quality must be evaluated separately.
P2 will then prove that one invalid semantic event leaves unrelated valid events inspectable.
