"""Password files vault: AES-256-GCM encrypted file storage."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

import encryption as enc
from database import get_db
from dependencies import get_current_user, require_admin_csrf
from models import AuditLog, PasswordFile, User

router = APIRouter(prefix="/api/password-files", tags=["password_files"])

MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB
ALLOWED_MIME = {
    "text/csv", "text/plain", "application/json",
    "application/zip", "application/x-zip-compressed",
    "application/octet-stream",
}


@router.get("")
def list_files(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    files = db.query(PasswordFile).filter(PasswordFile.user_id == user.id).order_by(PasswordFile.created_at.desc()).all()
    return [_fmt(f) for f in files]


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_csrf),
):
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 50 MB)")
    sha = enc.sha256_hex(data)
    encrypted = enc.encrypt(data)
    pf = PasswordFile(
        user_id=user.id, filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(data), sha256=sha, encrypted_data=encrypted,
    )
    db.add(pf)
    db.commit()
    db.refresh(pf)
    _audit(db, user.id, "PWFILE_UPLOADED", f"Fichier '{file.filename}' chargé", request)
    return _fmt(pf)


@router.get("/{file_id}/download")
def download_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pf = db.query(PasswordFile).filter(PasswordFile.id == file_id, PasswordFile.user_id == user.id).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    decrypted = enc.decrypt(pf.encrypted_data)
    return Response(
        content=decrypted, media_type=pf.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{pf.filename}"'},
    )


@router.delete("/{file_id}")
def delete_file(file_id: int, request: Request,
                db: Session = Depends(get_db), user: User = Depends(require_admin_csrf)):
    pf = db.query(PasswordFile).filter(PasswordFile.id == file_id, PasswordFile.user_id == user.id).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    name = pf.filename
    db.delete(pf)
    db.commit()
    _audit(db, user.id, "PWFILE_DELETED", f"Fichier '{name}' supprimé", request)
    return {"ok": True}


def _fmt(f: PasswordFile) -> dict:
    return {
        "id": f.id, "filename": f.filename, "mime_type": f.mime_type,
        "size_bytes": f.size_bytes, "sha256": f.sha256, "created_at": f.created_at,
    }


def _audit(db: Session, user_id: int, action: str, desc: str, request: Request):
    db.add(AuditLog(user_id=user_id, action=action, description=desc,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent") if request else None))
    db.commit()
