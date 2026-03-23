"""Physical assets router: CRUD, events, encrypted documents."""
import hashlib
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import encryption as enc
from database import get_db
from dependencies import get_current_user
from models import AssetDocument, AssetEvent, AuditLog, PhysicalAsset, User

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_FILE_BYTES = 20 * 1024 * 1024   # 20 MB

ALLOWED_MIME = {
    "application/pdf", "image/jpeg", "image/png", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv", "text/plain",
}


class AssetCreate(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    estimated_value: Optional[float] = None
    coffre_id: Optional[int] = None

class AssetUpdate(AssetCreate):
    pass

class EventCreate(BaseModel):
    type: str         # PURCHASE | SALE | VALUATION
    amount: Optional[float] = None
    date: str         # ISO date
    notes: Optional[str] = None


# ── Assets CRUD ───────────────────────────────────────────

@router.get("")
def list_assets(
    search: Optional[str] = None,
    category: Optional[str] = None,
    coffre_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(PhysicalAsset)
    if search:
        q = q.filter(PhysicalAsset.name.ilike(f"%{search}%"))
    if category:
        q = q.filter(PhysicalAsset.category == category)
    if coffre_id:
        q = q.filter(PhysicalAsset.coffre_id == coffre_id)
    assets = q.order_by(PhysicalAsset.name).all()
    return [_fmt_asset(a) for a in assets]


@router.post("", status_code=201)
def create_asset(data: AssetCreate, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    asset = PhysicalAsset(**data.model_dump(), user_id=user.id)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _audit(db, user.id, "ASSET_CREATED", f"Actif créé: {asset.name}", request)
    return _fmt_asset(asset)


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = db.query(PhysicalAsset).filter(PhysicalAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    return _fmt_asset(asset)


@router.put("/{asset_id}")
def update_asset(asset_id: int, data: AssetUpdate, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    asset = db.query(PhysicalAsset).filter(PhysicalAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    for k, v in data.model_dump().items():
        setattr(asset, k, v)
    db.commit()
    return _fmt_asset(asset)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    asset = db.query(PhysicalAsset).filter(PhysicalAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    db.delete(asset)
    db.commit()
    _audit(db, user.id, "ASSET_DELETED", f"Actif supprimé: {asset.name}", request)
    return {"ok": True}


# ── Events ────────────────────────────────────────────────

@router.post("/{asset_id}/events", status_code=201)
def add_event(asset_id: int, data: EventCreate, request: Request,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    asset = db.query(PhysicalAsset).filter(PhysicalAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    from datetime import date
    ev = AssetEvent(asset_id=asset_id, type=data.type,
                    amount=data.amount, date=date.fromisoformat(data.date), notes=data.notes)
    db.add(ev)
    # Update estimated value on VALUATION event
    if data.type == "VALUATION" and data.amount is not None:
        asset.estimated_value = data.amount
    db.commit()
    db.refresh(ev)
    return {"id": ev.id, "type": ev.type, "amount": ev.amount, "date": str(ev.date), "notes": ev.notes}


@router.delete("/{asset_id}/events/{event_id}")
def delete_event(asset_id: int, event_id: int, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    ev = db.query(AssetEvent).filter(AssetEvent.id == event_id, AssetEvent.asset_id == asset_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    db.delete(ev)
    db.commit()
    return {"ok": True}


# ── Documents ─────────────────────────────────────────────

@router.get("/{asset_id}/documents")
def list_documents(asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.query(AssetDocument).filter(AssetDocument.asset_id == asset_id).all()
    return [_fmt_doc(d) for d in docs]


@router.post("/{asset_id}/documents", status_code=201)
async def upload_document(
    asset_id: int,
    file: UploadFile = File(...),
    document_type: str = Form(default=""),
    notes: str = Form(default=""),
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    asset = db.query(PhysicalAsset).filter(PhysicalAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Type de fichier non autorisé: {file.content_type}")
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 20 MB)")
    sha = enc.sha256_hex(data)
    encrypted = enc.encrypt(data)
    doc = AssetDocument(
        asset_id=asset_id, user_id=user.id,
        filename=file.filename, mime_type=file.content_type,
        size_bytes=len(data), sha256=sha, encrypted_data=encrypted,
        document_type=document_type or None, notes=notes or None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    _audit(db, user.id, "DOCUMENT_UPLOADED", f"Document '{file.filename}' ajouté à actif #{asset_id}", request)
    return _fmt_doc(doc)


@router.get("/{asset_id}/documents/{doc_id}/download")
def download_document(asset_id: int, doc_id: int,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.query(AssetDocument).filter(AssetDocument.id == doc_id, AssetDocument.asset_id == asset_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    decrypted = enc.decrypt(doc.encrypted_data)
    return Response(
        content=decrypted, media_type=doc.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.delete("/{asset_id}/documents/{doc_id}")
def delete_document(asset_id: int, doc_id: int, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "USER":
        raise HTTPException(status_code=403, detail="Lecture seule")
    doc = db.query(AssetDocument).filter(AssetDocument.id == doc_id, AssetDocument.asset_id == asset_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    db.delete(doc)
    db.commit()
    return {"ok": True}


# ── Formatters ────────────────────────────────────────────

def _fmt_asset(a: PhysicalAsset) -> dict:
    return {
        "id": a.id, "name": a.name, "category": a.category,
        "description": a.description, "estimated_value": a.estimated_value,
        "coffre_id": a.coffre_id, "user_id": a.user_id,
        "created_at": a.created_at, "updated_at": a.updated_at,
        "events": [
            {"id": e.id, "type": e.type, "amount": e.amount, "date": str(e.date), "notes": e.notes}
            for e in a.events
        ],
        "documents": [_fmt_doc(d) for d in a.documents],
    }


def _fmt_doc(d: AssetDocument) -> dict:
    return {
        "id": d.id, "filename": d.filename, "mime_type": d.mime_type,
        "size_bytes": d.size_bytes, "sha256": d.sha256,
        "document_type": d.document_type, "notes": d.notes, "created_at": d.created_at,
    }


def _audit(db: Session, user_id: int, action: str, desc: str, request: Request):
    db.add(AuditLog(user_id=user_id, action=action, description=desc,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent") if request else None))
    db.commit()
