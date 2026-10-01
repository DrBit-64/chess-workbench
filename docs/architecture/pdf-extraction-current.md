# Current PDF extraction boundaries

The browser and POST /api/pdf-extractions create independent v8 source-relation jobs only. Appending to a v8 extraction document creates a v9 relation-continuation job. The model reads source evidence and returns source-linked relations; the compiler binds those relations to legal positions. Candidate content enters the knowledge base only after review and approval.

The shared PDF evidence layer renders pages, keeps OCR and image evidence, and stores immutable artifacts. The current relation pipeline is implemented by extraction/relations.py, extraction/source_compiler.py and services/pdf_source_extraction.py. Incremental document ownership, predecessor context and final commit live in services/pdf_documents.py and services/pdf_incremental_extraction.py.

Historical CCEF candidate generation for existing v2/v3/v4 jobs lives in services/pdf_legacy_extraction.py. Existing v5/v7 document append jobs retain their saved version and can resume. Historical v4/v6 documents may still append through their original v5/v7 protocol so an existing document is not stranded; this is a compatibility path, not a selectable independent extraction mode. Read, review and publication services continue to accept historical artifacts and CCEF versions; no stored result is rewritten during cleanup. The website no longer offers legacy extraction creation.

Use a saved provider response for compiler-only repairs. Do not call a model merely to prove a refactor. Investigate a new extraction failure from its source pages, saved response and current review result.
