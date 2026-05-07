import uuid
import aiofiles
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import get_settings
from app.models.models import Vehicle, MaintenanceSchedule, MaintenanceEntry, EntryAttachment
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


async def _resolve_schedules(
    schedule_ids: list[int], vehicle_id: int, db: AsyncSession
) -> list[MaintenanceSchedule]:
    """Fetch and validate that all requested schedule IDs belong to this vehicle."""
    if not schedule_ids:
        return []
    result = await db.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.id.in_(schedule_ids),
            MaintenanceSchedule.vehicle_id == vehicle_id,
        )
    )
    found = result.scalars().all()
    if len(found) != len(schedule_ids):
        found_ids = {s.id for s in found}
        missing = [sid for sid in schedule_ids if sid not in found_ids]
        raise HTTPException(
            status_code=404,
            detail=f"Schedule IDs not found for this vehicle: {missing}",
        )
    return list(found)


async def _entry_to_out(entry: MaintenanceEntry, db: AsyncSession) -> EntryOut:
    """Eagerly load all relationships and refresh server-set columns while the session is live."""
    await db.refresh(entry)  # reloads all columns (incl. server defaults like created_at)
    await db.refresh(entry, ["attachments", "schedules"])  # load relationships
    return EntryOut.model_validate({
        "id": entry.id,
        "vehicle_id": entry.vehicle_id,
        "schedule_ids": [s.id for s in entry.schedules],
        "title": entry.title,
        "notes": entry.notes,
        "odometer": entry.odometer,
        "cost": entry.cost,
        "shop_name": entry.shop_name,
        "performed_at": entry.performed_at,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "attachments": [
            {
                "id": a.id,
                "entry_id": a.entry_id,
                "filename": a.filename,
                "stored_name": a.stored_name,
                "mime_type": a.mime_type,
                "file_size": a.file_size,
                "uploaded_at": a.uploaded_at,
            }
            for a in entry.attachments
        ],
    })


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
    out = []
    for entry in entries:
        out.append(await _entry_to_out(entry, db))
    return out


@router.post(
    "/vehicles/{vehicle_id}/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    vehicle_id: int, payload: EntryCreate, db: AsyncSession = Depends(get_db)
):
    await _get_vehicle_or_404(vehicle_id, db)
    schedules = await _resolve_schedules(payload.schedule_ids, vehicle_id, db)

    entry_data = payload.model_dump(exclude={"schedule_ids"})
    entry = MaintenanceEntry(vehicle_id=vehicle_id, **entry_data)
    entry.schedules = schedules
    db.add(entry)
    await db.flush()
    return await _entry_to_out(entry, db)


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return await _entry_to_out(entry, db)


@router.put("/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: int, payload: EntryUpdate, db: AsyncSession = Depends(get_db)
):
    entry = await db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    update_data = payload.model_dump(exclude_unset=True, exclude={"schedule_ids"})
    for field, value in update_data.items():
        setattr(entry, field, value)

    # Only replace schedule links if schedule_ids was explicitly provided
    if payload.schedule_ids is not None:
        await db.refresh(entry, ["schedules"])  # load current before replacing
        schedules = await _resolve_schedules(payload.schedule_ids, entry.vehicle_id, db)
        entry.schedules = schedules

    await db.flush()
    return await _entry_to_out(entry, db)


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