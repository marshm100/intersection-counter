"""Event-audit API for /static/audit.html (backend/services/event_audit.py)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.services import event_audit as ea

router = APIRouter()


def _require_project(project_id: str) -> None:
    d = PROJECTS_DIR / project_id
    if not d.exists() or not (d / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")


class AnswerIn(BaseModel):
    verdict: str
    true_origin_leg_id: Optional[int] = None
    true_dest_leg_id: Optional[int] = None
    note: str = ""


@router.get("/projects/{project_id}/audit-items")
def list_audit_items(project_id: str, batch: Optional[str] = None):
    _require_project(project_id)
    return {"items": ea.list_items(project_id, batch), "verdicts": list(ea.VERDICTS)}


@router.get("/projects/{project_id}/audit-items/{item_id}")
def get_audit_item(project_id: str, item_id: int):
    _require_project(project_id)
    item = ea.get_item(project_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("/projects/{project_id}/audit-items/{item_id}/answer")
def answer_audit_item(project_id: str, item_id: int, body: AnswerIn):
    _require_project(project_id)
    try:
        return ea.answer_item(project_id, item_id, body.verdict, body.true_origin_leg_id,
                              body.true_dest_leg_id, body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Item not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
