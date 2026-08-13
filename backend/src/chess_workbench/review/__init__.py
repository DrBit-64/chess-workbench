"""Pure consumer-side CCEF review inspection (Stage 8D-1).

Exports only the frozen inspection public interface.  These names are review
package exports and must not be added to the extraction package exports.
"""

from .inspection import (
    REVIEW_INSPECTION_VERSION,
    ReviewInspection,
    ReviewIssue,
    ReviewIssueScope,
    ReviewIssueSeverity,
    inspect_review_candidate,
)

__all__ = [
    "REVIEW_INSPECTION_VERSION",
    "ReviewInspection",
    "ReviewIssue",
    "ReviewIssueScope",
    "ReviewIssueSeverity",
    "inspect_review_candidate",
]
