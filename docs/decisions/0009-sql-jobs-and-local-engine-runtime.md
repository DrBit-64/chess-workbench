# ADR 0009: SQL jobs and a bounded local engine runtime

## Status

Accepted — 2026-08-10

## Context

Stage 6 introduces work that can outlive one HTTP request: deep Stockfish analysis, game review,
and later OCR/AI import. ChessWorkbench is a local-first modular monolith and already treats SQL as
the authoritative store. Adding Redis, a broker, or a second source of truth would make local use
and recovery harder. UCI engines are also untrusted child processes: they can hang, print malformed
output, or exit while a job is running.

The UI needs both fast analysis and reliable background work. It also needs Lichess-style MultiPV
controls without copying Lichess' browser-worker implementation into a server-owned architecture.

## Decision

1. A generic `jobs` table is the durable queue. Claims, heartbeats, cancellation and terminal
   transitions use conditional SQL updates. A lease has an owner and expiry time; expired running
   jobs become claimable again until `max_attempts` is exhausted.
2. The state machine is explicit: `queued -> running -> succeeded|failed|cancelled`, with
   `running -> queued` only for lease recovery. Cancellation is idempotent. Completed jobs never
   re-enter the queue.
3. An `invalidation_events` outbox is written in the same SQL transaction as durable changes.
   WebSocket clients receive only event identifiers/resource keys and refetch through HTTP. A
   disconnected socket therefore cannot affect correctness.
4. Stockfish runs as one UCI subprocess per analysis operation. Every operation has bounded
   Threads, Hash, MultiPV and time/depth; cancellation and every failure path close the transport.
   The default interactive profile is Threads=1, Hash=128 MB, MultiPV=4, 800 ms, Ponder=false.
5. Analysis cache identity includes the complete six-field FEN, engine name and reported version,
   and every option/limit that can affect a result. Scores are persisted and exposed from White's
   point of view, including mate and WDL data, with UCI and SAN principal variations.
6. Syzygy is consulted first only when the configured local table set can answer the position.
   Missing files, unsupported castling rights and probe errors are an explicit unavailable result
   and fall back to Stockfish.
7. Stage 6D engine games and reviews are durable SQL aggregates. Saving a finding creates a draft
   traditional course/module/note through the existing Knowledge layer. Exercise creation remains
   the Stage 5-dependent 6E integration tail.
8. The repository pins the Stockfish release/archive metadata but does not commit the binary or
   large Syzygy tables. Installation writes only to gitignored `data/engines`/`data/tablebases`.
9. User-facing task deletion is recoverable archival, orthogonal to the five-state execution
   machine. Archiving a queued Job first transitions it to `cancelled`; archiving a running Job
   records the ordinary cancellation request so its owning worker cancels and awaits the handler;
   terminal Jobs retain their terminal state. `archived_at` removes all three forms from discovery
   lists without deleting the Job, domain receipt or immutable artifacts. Direct receipt reads may
   remain available for audit. The first public archive operation is scoped to PDF extraction runs.

## UI mapping

The analysis workspace uses the same information hierarchy as Lichess computer analysis: a
vertical evaluation gauge beside the board, compact engine/depth status above the variations, and
one score plus a clickable SAN line per PV. The settings drawer exposes engine, search time,
MultiPV (1–5), Threads and Hash. ChessWorkbench defaults to four variations because comparative
study is the primary use case; this intentionally differs from Lichess' stored default of one.

## Consequences

- A worker can be restarted safely and Stage 8 can reuse the same queue.
- SQL polling remains a complete fallback when WebSocket delivery is absent.
- Local analysis requires an installed UCI executable; API capability metadata explains how to
  install it instead of silently returning fabricated analysis.
- Tablebase coverage is limited by the files the user has installed.
- 6E cannot be marked complete until the Stage 5 Exercise model exists.
