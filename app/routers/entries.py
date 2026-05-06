import uuid
import aiofiles
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import get_settings
from app.models.models import Vehicle, MaintenanceEntry, EntryAttachment
from app.schemas.schemas import EntryCreate, EntryUpdate, EntryOut, AttachmentOut, MileagePoint

router = APIRouter(tags=["Entries"])
settings = get_settings()

ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf",
}


async def _get_vehicle_or_404(vehicle_id: int, db: AsyncSession) -> Vehicle:
    v = await db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return v


# ─── Entries ───────────────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/entries", response_model=list[EntryOut])
async def list_entries(
    vehicle_id: int,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    await _get_vehicle_or_404(vehicle_id, db)
    result = await db.execute(
        select(MaintenanceEntry)
        .where(MaintenanceEntry.vehicle_id == vehicle_id)
        .order_by(MaintenanceEntry.performed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()
    # Eagerly load attachments
    for entry in entries:
        await db.refresh(entry, ["attachments"])
    return entries


@router.post(
    "/vehicles/{vehicle_id}/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    vehicle_id: int, payload: EntryCreate, db: AsyncSession = Depends(get_db)
):
    await _get_vehicle_or_404(vehicle_id, db)
    entry = MaintenanceEntry(vehicle_id=vehicle_id, **payload.model_dump())
    db.add(entry)
    await db.flush()
    await db.refresh(entry, ["attachments"])
    return entry


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.refresh(entry, ["attachments"])
    return entry


@router.put("/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: int, payload: EntryUpdate, db: AsyncSession = Depends(get_db)
):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.flush()
    await db.refresh(entry, ["attachments"])
    return entry


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)


# ─── Mileage history (for chart) ──────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/mileage", response_model=list[MileagePoint])
async def mileage_history(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    await _get_vehicle_or_404(vehicle_id, db)
    result = await db.execute(
        select(MaintenanceEntry.performed_at, MaintenanceEntry.odometer)
        .where(
            MaintenanceEntry.vehicle_id == vehicle_id,
            MaintenanceEntry.odometer.is_not(None),
        )
        .order_by(MaintenanceEntry.performed_at.asc())
    )
    return [MileagePoint(performed_at=r.performed_at, odometer=r.odometer) for r in result.all()]


# ─── Attachments ──────────────────────────────────────────────────────────────

@router.post(
    "/entries/{entry_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    entry_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPEG, PNG, WebP, GIF, PDF",
        )

    contents = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_mb} MB limit",
        )

    ext = Path(file.filename or "file").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    upload_path = Path(settings.upload_dir) / stored_name
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(upload_path, "wb") as f:
        await f.write(contents)

    attachment = EntryAttachment(
        entry_id=entry_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        mime_type=file.content_type,
        file_size=len(contents),
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    return attachment


@router.get("/attachments/{attachment_id}/file")
async def download_attachment(
    attachment_id: int, db: AsyncSession = Depends(get_db)
):
    att = await db.get(EntryAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    file_path = Path(settings.upload_dir) / att.stored_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path=str(file_path), filename=att.filename, media_type=att.mime_type)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(attachment_id: int, db: AsyncSession = Depends(get_db)):
    att = await db.get(EntryAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    file_path = Path(settings.upload_dir) / att.stored_name
    if file_path.exists():
        file_path.unlink()
    await db.delete(att)
