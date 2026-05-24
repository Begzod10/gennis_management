"""Mobile permission helpers.

Single, conservative rule across all three systems:
- General mutation (update / delete / status / event posts):
    caller must be creator, executor, or reviewer of the mission.
- Approve / decline:
    caller must be reviewer or creator.
- Complete:
    caller must be executor.
- Redirect:
    caller must be creator.

This is intentionally stricter than the management web router (which has
role-based gating) — mobile is a smaller surface and we'd rather 403 a few
legitimate-but-edge requests than open the door to "any JWT can mutate any
mission". Creator/executor/reviewer is the only invariant we trust across
all three source schemas.
"""
from typing import Optional

from fastapi import HTTPException, status

from app.mobile.schemas import MobileIdentity


def _ids(record) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Pull (creator_id, executor_id, reviewer_id) off the record.

    Works for management `Mission`, `GennisMission`, and `TuronMission` — all
    three expose the same three attributes (just different column types).
    """
    return (
        getattr(record, "creator_id", None),
        getattr(record, "executor_id", None),
        getattr(record, "reviewer_id", None),
    )


def _is_participant(identity: MobileIdentity, record) -> bool:
    creator, executor, reviewer = _ids(record)
    me = identity.external_id
    return me in (creator, executor, reviewer)


def assert_can_mutate(identity: MobileIdentity, record) -> None:
    if not _is_participant(identity, record):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant on this mission",
        )


def assert_can_approve(identity: MobileIdentity, record) -> None:
    creator, _executor, reviewer = _ids(record)
    if identity.external_id not in (creator, reviewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the reviewer or creator can approve / decline",
        )


def assert_can_complete(identity: MobileIdentity, record) -> None:
    _creator, executor, _reviewer = _ids(record)
    if identity.external_id != executor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the executor can complete this mission",
        )


def assert_can_redirect(identity: MobileIdentity, record) -> None:
    creator, _executor, _reviewer = _ids(record)
    if identity.external_id != creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator can redirect this mission",
        )
