"""
Combined cross-system views (Gennis + Turon).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional

from ...database import get_gennis_write_db, get_turon_write_db
from ...external_models import gennis as G
from ...external_models import turon as T

router = APIRouter(prefix="/combined", tags=["Combined"])


@router.get("/directors")
def all_directors(
    location_id: Optional[int] = Query(None, description="Filter Gennis managers by location"),
    branch_id: Optional[int] = Query(None, description="Filter Turon directors by branch"),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """
    Returns all Gennis managers (profession='manager') and all Turon directors
    (group='direktor') in a unified list.
    """
    # ── Gennis managers ───────────────────────────────────────────────────────
    gq = (
        gennis_db.query(G.Staff, G.Users, G.GennisProfessions, G.GennisRoles, G.Locations)
        .join(G.Users, G.Staff.user_id == G.Users.id)
        .join(G.GennisProfessions, G.Staff.profession_id == G.GennisProfessions.id)
        .join(G.Locations, G.Users.location_id == G.Locations.id)
        .outerjoin(G.GennisRoles, G.Users.role_id == G.GennisRoles.id)
        .filter(
            G.GennisProfessions.name.ilike("manager"),
            or_(G.Staff.deleted == False, G.Staff.deleted == None),
            or_(G.Users.deleted == False, G.Users.deleted == None),
        )
    )
    if location_id:
        gq = gq.filter(G.Users.location_id == location_id)

    gennis_rows = gq.order_by(G.Users.name).all()

    gennis_result = [
        {
            "source": "gennis",
            "id": user.id,
            "name": user.name.title() if user.name else None,
            "surname": user.surname.title() if user.surname else None,
            "role": profession.name,
            "type_role": role.type_role if role else None,
            "location_id": user.location_id,
            "location_name": location.name,
            "branch_id": None,
            "branch_name": None,
        }
        for staff, user, profession, role, location in gennis_rows
    ]

    # ── Turon directors ───────────────────────────────────────────────────────
    tq = (
        turon_db.query(T.CustomUser, T.ManyBranch, T.Branch)
        .join(T.CustomAutoGroup, T.CustomAutoGroup.user_id == T.CustomUser.id)
        .join(T.AuthGroup, T.AuthGroup.id == T.CustomAutoGroup.group_id)
        .join(T.ManyBranch, T.ManyBranch.user_id == T.CustomUser.id)
        .join(T.Branch, T.Branch.id == T.ManyBranch.branch_id)
        .filter(
            T.AuthGroup.name == "Direktor",
            T.CustomUser.is_active == True,
            or_(T.CustomAutoGroup.deleted == False, T.CustomAutoGroup.deleted == None),
        )
    )
    if branch_id:
        tq = tq.filter(T.ManyBranch.branch_id == branch_id)

    turon_rows = tq.order_by(T.CustomUser.name).all()

    turon_result = [
        {
            "source": "turon",
            "id": user.id,
            "name": user.name,
            "surname": user.surname,
            "role": "direktor",
            "type_role": None,
            "location_id": None,
            "location_name": None,
            "branch_id": branch.id,
            "branch_name": branch.name,
        }
        for user, many_branch, branch in turon_rows
    ]

    all_directors = sorted(
        gennis_result + turon_result,
        key=lambda x: (x["name"] or ""),
    )

    return {
        "total": len(all_directors),
        "gennis_count": len(gennis_result),
        "turon_count": len(turon_result),
        "results": all_directors,
    }
