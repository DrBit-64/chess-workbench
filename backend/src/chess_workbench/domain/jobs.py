from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


class JobEvent(StrEnum):
    CLAIM = "claim"
    SUCCEED = "succeed"
    FAIL_RETRYABLE = "fail_retryable"
    FAIL_FINAL = "fail_final"
    CANCEL = "cancel"
    LEASE_EXPIRED_RETRY = "lease_expired_retry"
    LEASE_EXPIRED_FINAL = "lease_expired_final"


_TRANSITIONS: dict[tuple[JobStatus, JobEvent], JobStatus] = {
    (JobStatus.QUEUED, JobEvent.CLAIM): JobStatus.RUNNING,
    (JobStatus.QUEUED, JobEvent.CANCEL): JobStatus.CANCELLED,
    (JobStatus.RUNNING, JobEvent.SUCCEED): JobStatus.SUCCEEDED,
    (JobStatus.RUNNING, JobEvent.FAIL_RETRYABLE): JobStatus.QUEUED,
    (JobStatus.RUNNING, JobEvent.FAIL_FINAL): JobStatus.FAILED,
    (JobStatus.RUNNING, JobEvent.CANCEL): JobStatus.CANCELLED,
    (JobStatus.RUNNING, JobEvent.LEASE_EXPIRED_RETRY): JobStatus.QUEUED,
    (JobStatus.RUNNING, JobEvent.LEASE_EXPIRED_FINAL): JobStatus.FAILED,
}


class InvalidJobTransition(ValueError):
    pass


def transition_job(status: JobStatus, event: JobEvent) -> JobStatus:
    """Return the next state or reject an illegal transition.

    Cancelling a terminal job is deliberately idempotent. All other attempts to
    mutate a terminal result remain illegal.
    """

    if event is JobEvent.CANCEL and status in TERMINAL_JOB_STATUSES:
        return status
    try:
        return _TRANSITIONS[(status, event)]
    except KeyError as error:
        raise InvalidJobTransition(f"cannot apply {event} to {status}") from error


@dataclass(frozen=True)
class RetryDecision:
    status: JobStatus
    should_retry: bool


def failure_decision(*, attempt_count: int, max_attempts: int) -> RetryDecision:
    if attempt_count < 1 or max_attempts < 1:
        raise ValueError("attempt counts must be positive after a claim")
    should_retry = attempt_count < max_attempts
    event = JobEvent.FAIL_RETRYABLE if should_retry else JobEvent.FAIL_FINAL
    return RetryDecision(transition_job(JobStatus.RUNNING, event), should_retry)
