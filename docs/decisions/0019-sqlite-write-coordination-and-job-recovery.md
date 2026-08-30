# ADR 0019: SQLite write coordination and artifact-backed Job recovery

## Status

Accepted — 2026-08-28

## Context

ChessWorkbench runs the HTTP API and one SQL worker in the same local process.  A PDF handler may
spend minutes outside SQL while the worker maintains a lease.  The previous SQLite configuration
used the rollback journal and a pool of independent connections; the worker also wrote a heartbeat
after every 100 ms cancellation poll.  A short write collision could therefore break supervision,
and the failure path then depended on another unbounded database write.  In the observed incident
the handler completed and committed all immutable candidate artifacts, but its detached supervisor
left the durable Job in `running` and prevented later queued work from being claimed.

This contradicts ADR 0009's restart-safe lease model and ADR 0013/0014's short-transaction and
artifact-replay requirements.  Repeating the provider call after complete candidate artifacts have
already committed would also create avoidable cost and a new immutable-artifact conflict.

## Decision

1. File-backed local SQLite connections use WAL, `synchronous=NORMAL`, foreign keys and a five-
   second busy timeout.  One pooled connection serializes sessions belonging to the authoritative
   local API process.  MySQL configuration and concurrency are unchanged.
2. `Database.run_write` is the common boundary for short, database-only critical writes.  SQLite
   calls are additionally protected by one process-local async lock and retry only a completely
   rolled-back `database is locked` transaction, at most three attempts with bounded backoff.
   Provider, engine, OCR, PDF and filesystem work is forbidden inside this callback.
3. Worker claim, heartbeat, success, failure and cancellation completion use that boundary.
   Cancellation remains responsive, but a lease heartbeat is written every ten seconds rather than
   on every 100 ms monitor poll.  A monitor or transition exception cancels and awaits the handler;
   a handler must never continue after its supervisor has lost ownership.  Exhausted transient
   SQLite write contention leaves the lease for ordinary expiry recovery instead of terminating the
   Sanic shutdown path.
4. Evidence and CCEF artifact registration remain independent short transactions.  A retry may
   replay identical slots but never overwrite a different binding.
5. Before invoking a configured provider, the PDF handler checks for the exact complete candidate
   slot set.  It verifies CAS path/hash/size/media type, canonical CCEF bytes, package/run/source/
   page/provenance binding and matching raw/normalized provenance.  A valid set reconstructs the
   versioned Job result and summary locally.  A partial or inconsistent set fails closed; it is
   never regenerated or overwritten.

## Consequences

- Normal local reads and writes no longer race across API-owned SQLite connections.  WAL also lets
  unrelated external readers proceed while the local writer commits.
- A long-lived service session can delay the single local connection, so services must continue to
  close SQL sessions before external computation.  This is observable queueing, not an SQLite lock
  cycle, and remains bounded by the worker lease rules.
- WAL and busy timeout do not make SQLite a multi-writer server.  A future deployment with multiple
  API/worker processes should use the supported MySQL configuration rather than increasing retry
  counts.
- Restarting after a crash may increment the Job attempt count through lease recovery, but a fully
  committed candidate completes without another provider request.

