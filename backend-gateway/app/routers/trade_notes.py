"""Trade notes (journal) endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List

from app.models.base import CamelModel
from app.services import db_service

router = APIRouter()


class NoteCreate(BaseModel):
    note_text: str = Field(max_length=2000)


class NoteResponse(CamelModel):
    id: int
    trade_id: str
    note_text: str
    created_at: str
    updated_at: str


@router.get("/trades/{trade_id}/notes", response_model=List[NoteResponse])
def list_notes(trade_id: str):
    try:
        return db_service.get_trade_notes(trade_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trades/{trade_id}/notes", response_model=NoteResponse, status_code=201)
def create_note(trade_id: str, body: NoteCreate):
    try:
        return db_service.create_trade_note(trade_id, body.note_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/trades/{trade_id}/notes/{note_id}", response_model=NoteResponse)
def update_note(trade_id: str, note_id: int, body: NoteCreate):
    try:
        result = db_service.update_trade_note(trade_id, note_id, body.note_text)
        if not result:
            raise HTTPException(status_code=404, detail="Note not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/trades/{trade_id}/notes/{note_id}")
def delete_note(trade_id: str, note_id: int):
    try:
        deleted = db_service.delete_trade_note(trade_id, note_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
