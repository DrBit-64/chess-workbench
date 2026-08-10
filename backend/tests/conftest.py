"""Shared backend-test lifecycle checks."""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def collect_unclosed_resources() -> Iterator[None]:
    """Collect unreachable resources while pytest can attribute their warnings."""

    yield
    gc.collect()
