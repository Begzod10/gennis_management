"""Read-only mobile endpoints for mission "events" and subtasks.

Each endpoint dispatches on `identity.system` to the right database. The
shapes are normalised — a Gennis comment row and a Turon comment row come
out as the same `MobileCommentOut` for the mobile client.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from datetime import date as _date_t

from app.database import (
    get_db,
    get_gennis_db,
    get_gennis_write_db,
    get_turon_db,
    get_turon_write_db,
)
from app.external_models.gennis import (
    GennisMissionAttachment,
    GennisMissionComment,
    GennisMissionHistory,
    GennisMissionProof,
    GennisMissionSubtask,
    GennisMissionSubtaskAttachment,
    GennisMissionSubtaskComment,
    GennisMissionSubtaskProof,
    Users as GennisUsers,
)
from app.external_models.turon import (
    CustomUser as TuronUser,
    TuronMissionAttachment,
    TuronMissionComment,
    TuronMissionHistory,
    TuronMissionProof,
    TuronMissionSubtask,
    TuronMissionSubtaskAttachment,
    TuronMissionSubtaskComment,
    TuronMissionSubtaskProof,
)
from app.external_models.gennis import GennisMission
from app.external_models.turon import TuronMission
from app.mobile._perms import assert_can_mutate
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import (
    MobileAttachmentCreate,
    MobileAttachmentOut,
    MobileCommentCreate,
    MobileCommentOut,
    MobileHistoryEntry,
    MobileIdentity,
    MobileProofCreate,
    MobileProofOut,
    MobileSubtaskCreate,
    MobileSubtaskOut,
    MobileSubtaskUpdate,
)
from app.models import (
    Mission,
    MissionAttachment,
    MissionComment,
    MissionHistory,
    MissionProof,
    MissionSubtask,
    MissionSubtaskAttachment,
    MissionSubtaskComment,
    MissionSubtaskProof,
    User,
)


# ── Resource lookups w/ 404 + permission guard ───────────────────────────────

def _load_mission(
    identity: MobileIdentity,
    mission_id: int,
    db: Session,
    gennis_db: Session,
    turon_db: Session,
):
    """Load a mission from the caller's home DB, 404 if missing,
    403 if the caller isn't a participant (creator/executor/reviewer)."""
    if identity.system == "management":
        m = db.query(Mission).filter(
            Mission.id == mission_id, Mission.deleted == False,
        ).first()
    elif identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(
            GennisMission.id == mission_id, GennisMission.deleted == False,
        ).first()
    else:
        m = turon_db.query(TuronMission).filter(
            TuronMission.id == mission_id, TuronMission.deleted == False,
        ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    assert_can_mutate(identity, m)
    return m


def _load_subtask(
    identity: MobileIdentity,
    subtask_id: int,
    db: Session,
    gennis_db: Session,
    turon_db: Session,
):
    """Load a subtask from the caller's home DB, 404 if missing,
    403 if the caller isn't a participant on the parent mission."""
    if identity.system == "management":
        s = db.query(MissionSubtask).filter(
            MissionSubtask.id == subtask_id, MissionSubtask.deleted == False,
        ).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        parent = db.query(Mission).filter(
            Mission.id == s.mission_id, Mission.deleted == False,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent mission not found")
        assert_can_mutate(identity, parent)
        return s
    if identity.system == "gennis":
        s = gennis_db.query(GennisMissionSubtask).filter(
            GennisMissionSubtask.id == subtask_id,
        ).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        parent = gennis_db.query(GennisMission).filter(
            GennisMission.id == s.mission_id, GennisMission.deleted == False,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent mission not found")
        assert_can_mutate(identity, parent)
        return s
    s = turon_db.query(TuronMissionSubtask).filter(
        TuronMissionSubtask.id == subtask_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Subtask not found")
    parent = turon_db.query(TuronMission).filter(
        TuronMission.id == s.mission_id, TuronMission.deleted == False,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent mission not found")
    assert_can_mutate(identity, parent)
    return s


router = APIRouter(prefix="/mobile", tags=["Mobile - Events"])


# ── Name resolvers ───────────────────────────────────────────────────────────

def _mgmt_name(db: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = db.query(User).filter(User.id == user_id).first()
    return f"{u.name} {u.surname or ''}".strip() if u else None


def _gennis_name(gdb: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = gdb.query(GennisUsers).filter(GennisUsers.id == user_id).first()
    return f"{u.name or ''} {u.surname or ''}".strip() or None if u else None


def _turon_name(tdb: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = tdb.query(TuronUser).filter(TuronUser.id == user_id).first()
    return f"{u.name or ''} {u.surname or ''}".strip() or None if u else None


# ── Mission history ──────────────────────────────────────────────────────────

@router.get("/missions/{mission_id}/history", response_model=List[MobileHistoryEntry])
def mission_history(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionHistory)
            .filter(MissionHistory.mission_id == mission_id)
            .order_by(MissionHistory.created_at.asc())
            .all()
        )
        return [
            MobileHistoryEntry(
                id=h.id, source="management",
                status=h.status, note=h.note,
                changed_by_name=_mgmt_name(db, h.changed_by_id),
                executor_name=_mgmt_name(db, h.executor_id),
                reviewer_name=_mgmt_name(db, h.reviewer_id),
                created_at=h.created_at,
            ) for h in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionHistory)
            .filter(GennisMissionHistory.mission_id == mission_id)
            .order_by(GennisMissionHistory.created_at.asc())
            .all()
        )
        return [
            MobileHistoryEntry(
                id=h.id, source="gennis",
                status=h.status, note=h.note,
                changed_by_name=h.changed_by_name,
                executor_name=_gennis_name(gennis_db, h.executor_id),
                reviewer_name=_gennis_name(gennis_db, h.reviewer_id),
                created_at=h.created_at,
            ) for h in rows
        ]
    # turon
    rows = (
        turon_db.query(TuronMissionHistory)
        .filter(TuronMissionHistory.mission_id == mission_id)
        .order_by(TuronMissionHistory.created_at.asc())
        .all()
    )
    return [
        MobileHistoryEntry(
            id=h.id, source="turon",
            status=None, note=h.note,
            changed_by_name=h.changed_by_name,
            executor_name=_turon_name(turon_db, h.executor_id),
            reviewer_name=_turon_name(turon_db, h.reviewer_id),
            created_at=h.created_at,
        ) for h in rows
    ]


# ── Mission comments ─────────────────────────────────────────────────────────

@router.get("/missions/{mission_id}/comments", response_model=List[MobileCommentOut])
def mission_comments(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionComment)
            .filter(MissionComment.mission_id == mission_id, MissionComment.deleted == False)
            .order_by(MissionComment.created_at.asc())
            .all()
        )
        return [
            MobileCommentOut(
                id=c.id, source="management",
                text=c.text, user_id=c.user_id,
                user_name=c.creator_name or _mgmt_name(db, c.user_id),
                attachment_path=c.attachment,
                created_at=c.created_at,
            ) for c in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionComment)
            .filter(GennisMissionComment.mission_id == mission_id)
            .order_by(GennisMissionComment.created_at.asc())
            .all()
        )
        return [
            MobileCommentOut(
                id=c.id, source="gennis",
                text=c.text, user_id=c.user_id,
                user_name=c.creator_name or _gennis_name(gennis_db, c.user_id),
                attachment_path=c.attachment_path,
                created_at=c.created_at,
            ) for c in rows
        ]
    # turon
    rows = (
        turon_db.query(TuronMissionComment)
        .filter(TuronMissionComment.mission_id == mission_id)
        .order_by(TuronMissionComment.created_at.asc())
        .all()
    )
    return [
        MobileCommentOut(
            id=c.id, source="turon",
            text=c.text, user_id=c.user_id,
            user_name=c.creator_name or _turon_name(turon_db, c.user_id),
            attachment_path=c.attachment,
            created_at=c.created_at,
        ) for c in rows
    ]


# ── Mission attachments & proofs ─────────────────────────────────────────────

@router.get("/missions/{mission_id}/attachments", response_model=List[MobileAttachmentOut])
def mission_attachments(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionAttachment)
            .filter(MissionAttachment.mission_id == mission_id, MissionAttachment.deleted == False)
            .order_by(MissionAttachment.uploaded_at.asc())
            .all()
        )
        return [
            MobileAttachmentOut(id=a.id, source="management",
                                file_path=a.file, note=a.note,
                                creator_name=a.creator_name, uploaded_at=a.uploaded_at)
            for a in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionAttachment)
            .filter(GennisMissionAttachment.mission_id == mission_id)
            .order_by(GennisMissionAttachment.uploaded_at.asc())
            .all()
        )
        return [
            MobileAttachmentOut(id=a.id, source="gennis",
                                file_path=a.file_path, note=a.note,
                                creator_name=a.creator_name, uploaded_at=a.uploaded_at)
            for a in rows
        ]
    rows = (
        turon_db.query(TuronMissionAttachment)
        .filter(TuronMissionAttachment.mission_id == mission_id)
        .order_by(TuronMissionAttachment.uploaded_at.asc())
        .all()
    )
    return [
        MobileAttachmentOut(id=a.id, source="turon",
                            file_path=a.file, note=a.note,
                            creator_name=a.creator_name, uploaded_at=a.uploaded_at)
        for a in rows
    ]


@router.get("/missions/{mission_id}/proofs", response_model=List[MobileProofOut])
def mission_proofs(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionProof)
            .filter(MissionProof.mission_id == mission_id, MissionProof.deleted == False)
            .order_by(MissionProof.created_at.asc())
            .all()
        )
        return [
            MobileProofOut(id=p.id, source="management",
                           file_path=p.file, comment=p.comment,
                           creator_name=p.creator_name, created_at=p.created_at)
            for p in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionProof)
            .filter(GennisMissionProof.mission_id == mission_id)
            .order_by(GennisMissionProof.created_at.asc())
            .all()
        )
        return [
            MobileProofOut(id=p.id, source="gennis",
                           file_path=p.file_path, comment=p.comment,
                           creator_name=p.creator_name, created_at=p.created_at)
            for p in rows
        ]
    rows = (
        turon_db.query(TuronMissionProof)
        .filter(TuronMissionProof.mission_id == mission_id)
        .order_by(TuronMissionProof.created_at.asc())
        .all()
    )
    return [
        MobileProofOut(id=p.id, source="turon",
                       file_path=p.file, comment=p.comment,
                       creator_name=p.creator_name, created_at=p.created_at)
        for p in rows
    ]


# ── Subtasks ─────────────────────────────────────────────────────────────────

@router.get("/missions/{mission_id}/subtasks", response_model=List[MobileSubtaskOut])
def mission_subtasks(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionSubtask)
            .filter(MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False)
            .order_by(MissionSubtask.order.asc(), MissionSubtask.id.asc())
            .all()
        )
        return [
            MobileSubtaskOut(
                id=s.id, source="management", mission_id=s.mission_id,
                title=s.title, description=s.description,
                status=s.status, is_done=bool(s.is_done), order=s.order or 0,
                deadline=s.deadline, finish_date=s.finish_date,
                creator_name=_mgmt_name(db, s.creator_id),
                executor_name=_mgmt_name(db, s.executor_id),
                created_at=s.created_at,
            ) for s in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionSubtask)
            .filter(GennisMissionSubtask.mission_id == mission_id)
            .order_by(GennisMissionSubtask.order.asc(), GennisMissionSubtask.id.asc())
            .all()
        )
        return [
            MobileSubtaskOut(
                id=s.id, source="gennis", mission_id=s.mission_id,
                title=s.title, description=s.description,
                status=s.status, is_done=bool(s.is_done), order=s.order or 0,
                deadline=s.deadline, finish_date=s.finish_date,
                creator_name=s.creator_name,
                executor_name=None,
                created_at=s.created_at,
            ) for s in rows
        ]
    rows = (
        turon_db.query(TuronMissionSubtask)
        .filter(TuronMissionSubtask.mission_id == mission_id)
        .order_by(TuronMissionSubtask.order.asc(), TuronMissionSubtask.id.asc())
        .all()
    )
    return [
        MobileSubtaskOut(
            id=s.id, source="turon", mission_id=s.mission_id,
            title=s.title, description=s.description,
            status=s.status, is_done=bool(s.is_done), order=s.order or 0,
            deadline=s.deadline, finish_date=s.finish_date,
            creator_name=s.creator_name,
            executor_name=None,
            created_at=s.created_at,
        ) for s in rows
    ]


@router.get("/subtasks/{subtask_id}", response_model=MobileSubtaskOut)
def subtask_detail(
    subtask_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        s = db.query(MissionSubtask).filter(
            MissionSubtask.id == subtask_id, MissionSubtask.deleted == False
        ).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        return MobileSubtaskOut(
            id=s.id, source="management", mission_id=s.mission_id,
            title=s.title, description=s.description,
            status=s.status, is_done=bool(s.is_done), order=s.order or 0,
            deadline=s.deadline, finish_date=s.finish_date,
            creator_name=_mgmt_name(db, s.creator_id),
            executor_name=_mgmt_name(db, s.executor_id),
            created_at=s.created_at,
        )
    if identity.system == "gennis":
        s = gennis_db.query(GennisMissionSubtask).filter(GennisMissionSubtask.id == subtask_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        return MobileSubtaskOut(
            id=s.id, source="gennis", mission_id=s.mission_id,
            title=s.title, description=s.description,
            status=s.status, is_done=bool(s.is_done), order=s.order or 0,
            deadline=s.deadline, finish_date=s.finish_date,
            creator_name=s.creator_name, executor_name=None,
            created_at=s.created_at,
        )
    s = turon_db.query(TuronMissionSubtask).filter(TuronMissionSubtask.id == subtask_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Subtask not found")
    return MobileSubtaskOut(
        id=s.id, source="turon", mission_id=s.mission_id,
        title=s.title, description=s.description,
        status=s.status, is_done=bool(s.is_done), order=s.order or 0,
        deadline=s.deadline, finish_date=s.finish_date,
        creator_name=s.creator_name, executor_name=None,
        created_at=s.created_at,
    )


# ── Subtask events (comments / attachments / proofs) ─────────────────────────

@router.get("/subtasks/{subtask_id}/comments", response_model=List[MobileCommentOut])
def subtask_comments(
    subtask_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionSubtaskComment)
            .filter(MissionSubtaskComment.subtask_id == subtask_id,
                    MissionSubtaskComment.deleted == False)
            .order_by(MissionSubtaskComment.created_at.asc())
            .all()
        )
        return [
            MobileCommentOut(
                id=c.id, source="management",
                text=c.text, user_id=c.user_id,
                user_name=c.creator_name or _mgmt_name(db, c.user_id),
                attachment_path=c.attachment,
                created_at=c.created_at,
            ) for c in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionSubtaskComment)
            .filter(GennisMissionSubtaskComment.subtask_id == subtask_id)
            .order_by(GennisMissionSubtaskComment.created_at.asc())
            .all()
        )
        return [
            MobileCommentOut(
                id=c.id, source="gennis",
                text=c.text, user_id=c.user_id,
                user_name=c.creator_name or _gennis_name(gennis_db, c.user_id),
                attachment_path=c.attachment_path,
                created_at=c.created_at,
            ) for c in rows
        ]
    rows = (
        turon_db.query(TuronMissionSubtaskComment)
        .filter(TuronMissionSubtaskComment.subtask_id == subtask_id)
        .order_by(TuronMissionSubtaskComment.created_at.asc())
        .all()
    )
    return [
        MobileCommentOut(
            id=c.id, source="turon",
            text=c.text, user_id=c.user_id,
            user_name=c.creator_name or _turon_name(turon_db, c.user_id),
            attachment_path=c.attachment,
            created_at=c.created_at,
        ) for c in rows
    ]


@router.get("/subtasks/{subtask_id}/attachments", response_model=List[MobileAttachmentOut])
def subtask_attachments(
    subtask_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionSubtaskAttachment)
            .filter(MissionSubtaskAttachment.subtask_id == subtask_id,
                    MissionSubtaskAttachment.deleted == False)
            .order_by(MissionSubtaskAttachment.uploaded_at.asc())
            .all()
        )
        return [
            MobileAttachmentOut(id=a.id, source="management",
                                file_path=a.file, note=a.note,
                                creator_name=a.creator_name, uploaded_at=a.uploaded_at)
            for a in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionSubtaskAttachment)
            .filter(GennisMissionSubtaskAttachment.subtask_id == subtask_id)
            .order_by(GennisMissionSubtaskAttachment.uploaded_at.asc())
            .all()
        )
        return [
            MobileAttachmentOut(id=a.id, source="gennis",
                                file_path=a.file_path, note=a.note,
                                creator_name=a.creator_name, uploaded_at=a.uploaded_at)
            for a in rows
        ]
    rows = (
        turon_db.query(TuronMissionSubtaskAttachment)
        .filter(TuronMissionSubtaskAttachment.subtask_id == subtask_id)
        .order_by(TuronMissionSubtaskAttachment.uploaded_at.asc())
        .all()
    )
    return [
        MobileAttachmentOut(id=a.id, source="turon",
                            file_path=a.file, note=a.note,
                            creator_name=a.creator_name, uploaded_at=a.uploaded_at)
        for a in rows
    ]


@router.get("/subtasks/{subtask_id}/proofs", response_model=List[MobileProofOut])
def subtask_proofs(
    subtask_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        rows = (
            db.query(MissionSubtaskProof)
            .filter(MissionSubtaskProof.subtask_id == subtask_id,
                    MissionSubtaskProof.deleted == False)
            .order_by(MissionSubtaskProof.created_at.asc())
            .all()
        )
        return [
            MobileProofOut(id=p.id, source="management",
                           file_path=p.file, comment=p.comment,
                           creator_name=p.creator_name, created_at=p.created_at)
            for p in rows
        ]
    if identity.system == "gennis":
        rows = (
            gennis_db.query(GennisMissionSubtaskProof)
            .filter(GennisMissionSubtaskProof.subtask_id == subtask_id)
            .order_by(GennisMissionSubtaskProof.created_at.asc())
            .all()
        )
        return [
            MobileProofOut(id=p.id, source="gennis",
                           file_path=p.file_path, comment=p.comment,
                           creator_name=p.creator_name, created_at=p.created_at)
            for p in rows
        ]
    rows = (
        turon_db.query(TuronMissionSubtaskProof)
        .filter(TuronMissionSubtaskProof.subtask_id == subtask_id)
        .order_by(TuronMissionSubtaskProof.created_at.asc())
        .all()
    )
    return [
        MobileProofOut(id=p.id, source="turon",
                       file_path=p.file, comment=p.comment,
                       creator_name=p.creator_name, created_at=p.created_at)
        for p in rows
    ]


# ── Write endpoints ──────────────────────────────────────────────────────────
#
# Each POST validates that the target mission/subtask exists in the caller's
# system before inserting. We deliberately do NOT cross-write into the other
# two databases — a comment posted by a Gennis user lands in the Gennis DB.
# Sync of management → external (and back) is the management router's job.

def _display_name(identity: MobileIdentity) -> str:
    return identity.name or "User"


# ── Mission comments ─────────────────────────────────────────────────────────

@router.post("/missions/{mission_id}/comments", response_model=MobileCommentOut, status_code=201)
def create_mission_comment(
    mission_id: int,
    data: MobileCommentCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_mission(identity, mission_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        c = MissionComment(
            mission_id=mission_id,
            user_id=identity.external_id,
            text=data.text,
            attachment=data.attachment_path,
            creator_name=creator_name,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return MobileCommentOut(
            id=c.id, source="management", text=c.text,
            user_id=c.user_id, user_name=creator_name,
            attachment_path=c.attachment, created_at=c.created_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionComment as _G
        c = _G(
            mission_id=mission_id,
            user_id=identity.external_id,
            text=data.text,
            attachment_path=data.attachment_path,
            creator_name=creator_name,
            created_at=datetime.utcnow(),
        )
        gennis_db.add(c)
        gennis_db.commit()
        gennis_db.refresh(c)
        return MobileCommentOut(
            id=c.id, source="gennis", text=c.text,
            user_id=c.user_id, user_name=creator_name,
            attachment_path=c.attachment_path, created_at=c.created_at,
        )
    from app.external_models.turon import TuronMissionComment as _T
    c = _T(
        mission_id=mission_id,
        user_id=identity.external_id,
        text=data.text,
        attachment=data.attachment_path,
        creator_name=creator_name,
        created_at=datetime.utcnow(),
    )
    turon_db.add(c)
    turon_db.commit()
    turon_db.refresh(c)
    return MobileCommentOut(
        id=c.id, source="turon", text=c.text,
        user_id=c.user_id, user_name=creator_name,
        attachment_path=c.attachment, created_at=c.created_at,
    )


# ── Mission attachments ──────────────────────────────────────────────────────

@router.post("/missions/{mission_id}/attachments", response_model=MobileAttachmentOut, status_code=201)
def create_mission_attachment(
    mission_id: int,
    data: MobileAttachmentCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_mission(identity, mission_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        a = MissionAttachment(
            mission_id=mission_id, file=data.file_path,
            note=data.note, creator_name=creator_name,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return MobileAttachmentOut(
            id=a.id, source="management", file_path=a.file,
            note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionAttachment as _G
        a = _G(
            mission_id=mission_id, file_path=data.file_path,
            note=data.note, creator_name=creator_name,
            uploaded_at=datetime.utcnow(),
        )
        gennis_db.add(a)
        gennis_db.commit()
        gennis_db.refresh(a)
        return MobileAttachmentOut(
            id=a.id, source="gennis", file_path=a.file_path,
            note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
        )
    from app.external_models.turon import TuronMissionAttachment as _T
    a = _T(
        mission_id=mission_id, file=data.file_path,
        note=data.note, creator_name=creator_name,
        uploaded_at=datetime.utcnow(),
    )
    turon_db.add(a)
    turon_db.commit()
    turon_db.refresh(a)
    return MobileAttachmentOut(
        id=a.id, source="turon", file_path=a.file,
        note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
    )


# ── Mission proofs ───────────────────────────────────────────────────────────

@router.post("/missions/{mission_id}/proofs", response_model=MobileProofOut, status_code=201)
def create_mission_proof(
    mission_id: int,
    data: MobileProofCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_mission(identity, mission_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        p = MissionProof(
            mission_id=mission_id, file=data.file_path,
            comment=data.comment, creator_name=creator_name,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return MobileProofOut(
            id=p.id, source="management", file_path=p.file,
            comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionProof as _G
        p = _G(
            mission_id=mission_id, file_path=data.file_path,
            comment=data.comment, creator_name=creator_name,
            created_at=datetime.utcnow(),
        )
        gennis_db.add(p)
        gennis_db.commit()
        gennis_db.refresh(p)
        return MobileProofOut(
            id=p.id, source="gennis", file_path=p.file_path,
            comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
        )
    from app.external_models.turon import TuronMissionProof as _T
    p = _T(
        mission_id=mission_id, file=data.file_path,
        comment=data.comment, creator_name=creator_name,
        created_at=datetime.utcnow(),
    )
    turon_db.add(p)
    turon_db.commit()
    turon_db.refresh(p)
    return MobileProofOut(
        id=p.id, source="turon", file_path=p.file,
        comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
    )


# ── Subtasks (create / update / delete) ──────────────────────────────────────

@router.post("/missions/{mission_id}/subtasks", response_model=MobileSubtaskOut, status_code=201)
def create_subtask(
    mission_id: int,
    data: MobileSubtaskCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_mission(identity, mission_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        s = MissionSubtask(
            mission_id=mission_id,
            creator_id=identity.external_id,
            executor_id=data.executor_id,
            title=data.title,
            description=data.description,
            deadline=data.deadline,
            order=data.order or 0,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return MobileSubtaskOut(
            id=s.id, source="management", mission_id=s.mission_id,
            title=s.title, description=s.description,
            status=s.status, is_done=bool(s.is_done), order=s.order or 0,
            deadline=s.deadline, finish_date=s.finish_date,
            creator_name=_mgmt_name(db, s.creator_id),
            executor_name=_mgmt_name(db, s.executor_id),
            created_at=s.created_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtask as _G
        s = _G(
            mission_id=mission_id,
            title=data.title,
            order=data.order or 0,
            creator_name=creator_name,
            created_at=datetime.utcnow(),
        )
        gennis_db.add(s)
        gennis_db.commit()
        gennis_db.refresh(s)
        return MobileSubtaskOut(
            id=s.id, source="gennis", mission_id=s.mission_id,
            title=s.title, description=None,
            status=None, is_done=bool(s.is_done), order=s.order or 0,
            deadline=None, finish_date=None,
            creator_name=s.creator_name, executor_name=None,
            created_at=s.created_at,
        )
    from app.external_models.turon import TuronMissionSubtask as _T
    s = _T(
        mission_id=mission_id,
        title=data.title,
        order=data.order or 0,
        creator_name=creator_name,
    )
    turon_db.add(s)
    turon_db.commit()
    turon_db.refresh(s)
    return MobileSubtaskOut(
        id=s.id, source="turon", mission_id=s.mission_id,
        title=s.title, description=None,
        status=None, is_done=bool(s.is_done), order=s.order or 0,
        deadline=None, finish_date=None,
        creator_name=s.creator_name, executor_name=None,
        created_at=None,
    )


@router.patch("/subtasks/{subtask_id}", response_model=MobileSubtaskOut)
def update_subtask(
    subtask_id: int,
    data: MobileSubtaskUpdate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    _load_subtask(identity, subtask_id, db, gennis_db, turon_db)

    if identity.system == "management":
        s = db.query(MissionSubtask).filter(
            MissionSubtask.id == subtask_id, MissionSubtask.deleted == False,
        ).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        for field, value in payload.items():
            setattr(s, field, value)
        if payload.get("is_done") and s.finish_date is None:
            s.finish_date = _date_t.today()
        db.commit()
        db.refresh(s)
        return MobileSubtaskOut(
            id=s.id, source="management", mission_id=s.mission_id,
            title=s.title, description=s.description,
            status=s.status, is_done=bool(s.is_done), order=s.order or 0,
            deadline=s.deadline, finish_date=s.finish_date,
            creator_name=_mgmt_name(db, s.creator_id),
            executor_name=_mgmt_name(db, s.executor_id),
            created_at=s.created_at,
        )

    # Fields not present in the external schemas (Flask Gennis / Django Turon).
    _UNSUPPORTED_EXT_FIELDS = {"description", "status", "deadline", "finish_date", "executor_id"}

    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtask as _G
        s = gennis_db.query(_G).filter(_G.id == subtask_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        for field in _UNSUPPORTED_EXT_FIELDS:
            payload.pop(field, None)
        for field, value in payload.items():
            setattr(s, field, value)
        gennis_db.commit()
        gennis_db.refresh(s)
        return MobileSubtaskOut(
            id=s.id, source="gennis", mission_id=s.mission_id,
            title=s.title, description=None,
            status=None, is_done=bool(s.is_done), order=s.order or 0,
            deadline=None, finish_date=None,
            creator_name=s.creator_name, executor_name=None,
            created_at=s.created_at,
        )

    from app.external_models.turon import TuronMissionSubtask as _T
    s = turon_db.query(_T).filter(_T.id == subtask_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Subtask not found")
    for field in _UNSUPPORTED_EXT_FIELDS:
        payload.pop(field, None)
    for field, value in payload.items():
        setattr(s, field, value)
    turon_db.commit()
    turon_db.refresh(s)
    return MobileSubtaskOut(
        id=s.id, source="turon", mission_id=s.mission_id,
        title=s.title, description=None,
        status=None, is_done=bool(s.is_done), order=s.order or 0,
        deadline=None, finish_date=None,
        creator_name=s.creator_name, executor_name=None,
        created_at=None,
    )


@router.delete("/subtasks/{subtask_id}", status_code=204)
def delete_subtask(
    subtask_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_subtask(identity, subtask_id, db, gennis_db, turon_db)
    if identity.system == "management":
        s = db.query(MissionSubtask).filter(
            MissionSubtask.id == subtask_id, MissionSubtask.deleted == False,
        ).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        s.deleted = True
        db.commit()
        return

    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtask as _G
        s = gennis_db.query(_G).filter(_G.id == subtask_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Subtask not found")
        gennis_db.delete(s)
        gennis_db.commit()
        return

    from app.external_models.turon import TuronMissionSubtask as _T
    s = turon_db.query(_T).filter(_T.id == subtask_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Subtask not found")
    turon_db.delete(s)
    turon_db.commit()


# ── Subtask comments / attachments / proofs ──────────────────────────────────

@router.post("/subtasks/{subtask_id}/comments", response_model=MobileCommentOut, status_code=201)
def create_subtask_comment(
    subtask_id: int,
    data: MobileCommentCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_subtask(identity, subtask_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        c = MissionSubtaskComment(
            subtask_id=subtask_id, user_id=identity.external_id,
            text=data.text, attachment=data.attachment_path,
            creator_name=creator_name,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return MobileCommentOut(
            id=c.id, source="management", text=c.text,
            user_id=c.user_id, user_name=creator_name,
            attachment_path=c.attachment, created_at=c.created_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtaskComment as _G
        c = _G(
            subtask_id=subtask_id, user_id=identity.external_id,
            text=data.text, attachment_path=data.attachment_path,
            creator_name=creator_name, created_at=datetime.utcnow(),
        )
        gennis_db.add(c)
        gennis_db.commit()
        gennis_db.refresh(c)
        return MobileCommentOut(
            id=c.id, source="gennis", text=c.text,
            user_id=c.user_id, user_name=creator_name,
            attachment_path=c.attachment_path, created_at=c.created_at,
        )
    from app.external_models.turon import TuronMissionSubtaskComment as _T
    c = _T(
        subtask_id=subtask_id, user_id=identity.external_id,
        text=data.text, attachment=data.attachment_path,
        creator_name=creator_name, created_at=datetime.utcnow(),
    )
    turon_db.add(c)
    turon_db.commit()
    turon_db.refresh(c)
    return MobileCommentOut(
        id=c.id, source="turon", text=c.text,
        user_id=c.user_id, user_name=creator_name,
        attachment_path=c.attachment, created_at=c.created_at,
    )


@router.post("/subtasks/{subtask_id}/attachments", response_model=MobileAttachmentOut, status_code=201)
def create_subtask_attachment(
    subtask_id: int,
    data: MobileAttachmentCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_subtask(identity, subtask_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        a = MissionSubtaskAttachment(
            subtask_id=subtask_id, file=data.file_path,
            note=data.note, creator_name=creator_name,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return MobileAttachmentOut(
            id=a.id, source="management", file_path=a.file,
            note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtaskAttachment as _G
        a = _G(
            subtask_id=subtask_id, file_path=data.file_path,
            note=data.note, creator_name=creator_name,
            uploaded_at=datetime.utcnow(),
        )
        gennis_db.add(a)
        gennis_db.commit()
        gennis_db.refresh(a)
        return MobileAttachmentOut(
            id=a.id, source="gennis", file_path=a.file_path,
            note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
        )
    from app.external_models.turon import TuronMissionSubtaskAttachment as _T
    a = _T(
        subtask_id=subtask_id, file=data.file_path,
        note=data.note, creator_name=creator_name,
        uploaded_at=datetime.utcnow(),
    )
    turon_db.add(a)
    turon_db.commit()
    turon_db.refresh(a)
    return MobileAttachmentOut(
        id=a.id, source="turon", file_path=a.file,
        note=a.note, creator_name=a.creator_name, uploaded_at=a.uploaded_at,
    )


@router.post("/subtasks/{subtask_id}/proofs", response_model=MobileProofOut, status_code=201)
def create_subtask_proof(
    subtask_id: int,
    data: MobileProofCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _load_subtask(identity, subtask_id, db, gennis_db, turon_db)
    creator_name = _display_name(identity)
    if identity.system == "management":
        p = MissionSubtaskProof(
            subtask_id=subtask_id, file=data.file_path,
            comment=data.comment, creator_name=creator_name,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return MobileProofOut(
            id=p.id, source="management", file_path=p.file,
            comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
        )
    if identity.system == "gennis":
        from app.external_models.gennis import GennisMissionSubtaskProof as _G
        p = _G(
            subtask_id=subtask_id, file_path=data.file_path,
            comment=data.comment, creator_name=creator_name,
            created_at=datetime.utcnow(),
        )
        gennis_db.add(p)
        gennis_db.commit()
        gennis_db.refresh(p)
        return MobileProofOut(
            id=p.id, source="gennis", file_path=p.file_path,
            comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
        )
    from app.external_models.turon import TuronMissionSubtaskProof as _T
    p = _T(
        subtask_id=subtask_id, file=data.file_path,
        comment=data.comment, creator_name=creator_name,
        created_at=datetime.utcnow(),
    )
    turon_db.add(p)
    turon_db.commit()
    turon_db.refresh(p)
    return MobileProofOut(
        id=p.id, source="turon", file_path=p.file,
        comment=p.comment, creator_name=p.creator_name, created_at=p.created_at,
    )
