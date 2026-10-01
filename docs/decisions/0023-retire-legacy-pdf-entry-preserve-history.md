# ADR 0023: Retire legacy PDF creation while preserving saved work

- Date: 2026-10-01
- Status: Accepted for the single-user local website

## Context

The browser still offered legacy v4 extraction even after v8/v9 became the accepted personal-use pipeline. The original PDF worker also mixed shared rendering and immutable evidence with older direct CCEF candidate generation. Saved runs, reviews and continuous documents still reference older versions.

## Decision

New independent extraction requests use v8 only; the API rejects the former legacy flag. Repeating a saved old run creates a new v8 task. A v8 document continues through v9.

Older results, review revisions, publications and queued job payloads keep their original version and remain readable or resumable. Existing v4/v6 documents may continue through their historical v5/v7 append protocol so cleanup does not strand a saved document. No stored package is converted or rewritten by this change.

Old v2/v3/v4 candidate generation lives in services/pdf_legacy_extraction.py. Old incremental CCEF generation lives in services/pdf_legacy_incremental.py. Shared evidence, source-relation generation and review remain in their current services.

## Consequences

The normal browser path has one extraction protocol. The old document append path is compatibility code and can be retired separately if the saved documents are migrated or no longer needed. Local focused tests cover the creation boundary and old reads; broad six-book extraction quality evaluation is still deferred.
