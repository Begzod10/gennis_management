"""Mobile user picker endpoints.

A mission creator on mobile needs to pick an executor and (optionally) a
reviewer. The picker must show only people the creator is actually allowed
to assign work to — otherwise the mobile UI lets the user type any id and
the server rejects it later, or worse, accepts it silently.

This router exposes one endpoint:

    GET /api/v1/mobile/users/eligible-executors

It dispatches on `identity.system`:

- management: reuses `_eligible_executors()` from the management router so
  the same ROLE_CAN_ASSIGN / project-member rules apply.
- gennis: returns active users from the Gennis `users` table joined to
  `roles`. The Gennis system does not currently encode an assignment
  hierarchy, so we return the active set — same as service_request mode on
  management. The mobile client should still respect the cross-system
  restriction (a Gennis user can only assign to Gennis users).
- turon: returns active users from Turon `user_customuser` with the first
  associated `auth_group.name` as the role label. Same lack of hierarchy as
  Gennis applies.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db, get_gennis_db, get_turon_db
from app.external_models.gennis import GennisRoles, Users as GennisUsers
from app.external_models.turon import AuthGroup, CustomUser as TuronUser, customuser_groups
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import MobileExecutorOut, MobileIdentity
from app.models import User
from app.routers.v1.management.missions import _eligible_executors


router = APIRouter(prefix="/mobile/users", tags=["Mobile - Users"])


def _mgmt_to_out(u: User) -> MobileExecutorOut:
    return MobileExecutorOut(
        id=u.id,
        system="management",
        name=u.name,
        surname=u.surname,
        role=u.role,
    )


def _gennis_to_out(u: GennisUsers, role_name: Optional[str]) -> MobileExecutorOut:
    return MobileExecutorOut(
        id=u.id,
        system="gennis",
        name=u.name,
        surname=u.surname,
        role=role_name,
    )


def _turon_to_out(u: TuronUser, role_name: Optional[str]) -> MobileExecutorOut:
    return MobileExecutorOut(
        id=u.id,
        system="turon",
        name=u.name,
        surname=u.surname,
        role=role_name,
    )


@router.get("/eligible-executors", response_model=List[MobileExecutorOut])
def list_eligible_executors(
    channel: str = Query(
        "line_management",
        description="management only — line_management | project | service_request",
    ),
    project_id: Optional[int] = Query(None, description="management only"),
    section_id: Optional[int] = Query(None, description="management only"),
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    """Users the caller can assign a mission to.

    The list is always scoped to the caller's home system — cross-system
    assignment is not supported on the mobile surface.
    """
    if identity.system == "management":
        creator = db.query(User).filter(User.id == identity.external_id).first()
        if not creator:
            raise HTTPException(status_code=404, detail="Creator not found")
        users = _eligible_executors(creator, channel, project_id, section_id, db)
        return [_mgmt_to_out(u) for u in users]

    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisUsers, GennisRoles.role)
            .outerjoin(GennisRoles, GennisRoles.id == GennisUsers.role_id)
            .filter(GennisUsers.deleted == False)
            .order_by(GennisUsers.name.asc(), GennisUsers.surname.asc())
            .all()
        )
        return [_gennis_to_out(u, role) for u, role in rows]

    # turon
    # CustomUser ↔ AuthGroup is M2M through user_customuser_groups. For the
    # picker label we surface the FIRST associated group name (alphabetical)
    # via a correlated subquery — keeps it to a single round-trip and avoids
    # N+1 lookups while still showing something useful in the dropdown.
    from sqlalchemy import select, func as _func

    first_group_sq = (
        select(AuthGroup.name)
        .join(customuser_groups, customuser_groups.c.group_id == AuthGroup.id)
        .where(customuser_groups.c.customuser_id == TuronUser.id)
        .order_by(AuthGroup.name.asc())
        .limit(1)
        .correlate(TuronUser)
        .scalar_subquery()
    )

    rows = (
        turon_db.query(TuronUser, first_group_sq.label("role_name"))
        .filter(TuronUser.is_active == True)
        .order_by(TuronUser.name.asc(), TuronUser.surname.asc())
        .all()
    )
    return [_turon_to_out(u, role) for u, role in rows]
