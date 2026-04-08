from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Notification
from app.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=List[NotificationOut])
def list_notifications(
    user_id: int = Query(...),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user_id, Notification.deleted == False)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    return q.order_by(Notification.created_at.desc()).all()


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_as_read(notification_id: int, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.deleted == False).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.patch("/read-all", response_model=dict)
def mark_all_read(user_id: int = Query(...), db: Session = Depends(get_db)):
    db.query(Notification).filter(
        Notification.user_id == user_id, Notification.is_read == False, Notification.deleted == False
    ).update({"is_read": True})
    db.commit()
    return {"detail": "All notifications marked as read"}


@router.delete("/{notification_id}", status_code=204)
def delete_notification(notification_id: int, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.deleted == False).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.deleted = True
    db.commit()
