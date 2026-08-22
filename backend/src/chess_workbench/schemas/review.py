"""Strict server-owned read-only review document contracts (8D-2A).

Composes the immutable normalized CCEF package, the accepted 8D-1 inspection
and verified rendered-page descriptors.  This module adds no route, storage
read, content serving, SQL, frontend or generated OpenAPI artifact, and never
recomputes the normalized CCEF hash (the future artifact-loading service owns
byte/hash verification).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from ..extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from ..review.inspection import ReviewInspection, inspect_review_candidate
from .domain import EntityId, Sha256, StrictContract

ReviewPageContentPath = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^/api/pdf-extractions/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"/review/pages/[1-9][0-9]*$"
        ),
        max_length=128,
    ),
]

ReviewPackage = Annotated[
    ExtractionPackage | ExtractionPackageV1_1,
    Field(discriminator="schema_version"),
]


class PdfReviewPageRead(StrictContract):
    physical_page: Annotated[int, Field(ge=1, le=20_000)]
    media_type: Literal["image/png"] = "image/png"
    byte_size: Annotated[int, Field(gt=0)]
    content_sha256: Sha256
    content_url: ReviewPageContentPath


class PdfReviewDocumentRead(StrictContract):
    run_id: EntityId
    normalized_ccef_sha256: Sha256
    package: ReviewPackage
    inspection: ReviewInspection
    pages: list[PdfReviewPageRead]

    @model_validator(mode="after")
    def _validate_review_document(self) -> PdfReviewDocumentRead:
        if self.package.package_id != self.run_id:
            raise ValueError("package_id does not match run_id")
        page_range = self.package.source.page_range
        if page_range is None:
            raise ValueError("source page range is missing")
        # Constant-extra-memory validation: CCEF page ranges are unbounded, so
        # never materialize or iterate a range-sized sequence.
        expected_count = page_range.end_page - page_range.start_page + 1
        if len(self.pages) != expected_count:
            raise ValueError(
                "page descriptors must cover the source range exactly once in ascending order"
            )
        for index, page in enumerate(self.pages):
            if page.physical_page != page_range.start_page + index:
                raise ValueError(
                    "page descriptors must cover the source range exactly once in ascending order"
                )
        run_path = str(self.run_id)
        for page in self.pages:
            expected_url = f"/api/pdf-extractions/{run_path}/review/pages/{page.physical_page}"
            if page.content_url != expected_url:
                raise ValueError("page content_url does not match the run and physical page")
        # Recompute live; the accepted inspection's normalized-candidate error
        # (ValueError) propagates instead of being hidden.
        if self.inspection != inspect_review_candidate(self.package):
            raise ValueError("inspection does not match the current review candidate")
        return self


__all__ = ["ReviewPageContentPath", "PdfReviewPageRead", "PdfReviewDocumentRead"]
