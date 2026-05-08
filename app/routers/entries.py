import csv
import io
import logging
import uuid
import aiofiles
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import get_settings
from app.models.models import Vehicle, MaintenanceSchedule, MaintenanceEntry, EntryAttachment
from app.schemas.schemas import (
    EntryCreate, EntryUpdate, EntryOut, AttachmentOut, MileagePoint,
    ImportResult, ImportRowError,
)

router = APIRouter(tags=["Entries"])
settings = get_settings()
logger = logging.getLogger(__name__)

ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf",
}

CSV_REQUIRED_COLS = {"Date", "Odometer", "Title"}
CSV_DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
    await db.refresh(entry)
    await db.refresh(entry, ["attachments", "schedules"])
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


def _parse_date(raw: str):
    for fmt in CSV_DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_odometer(raw: str):
    try:
        return int(raw.strip().replace(",", ""))
    except ValueError:
        return None


# ─── Entries ──────────────────────────────────────────────────────────────────

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
    return [await _entry_to_out(e, db) for e in entries]


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


@router.post(
    "/vehicles/{vehicle_id}/entries/import",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_entries_csv(
    vehicle_id: int,
    file: UploadFile = File(...),
    skip_errors: bool = False,
    db: AsyncSession = Depends(get_db),
):
    await _get_vehicle_or_404(vehicle_id, db)
    logger.info(
        "CSV import started: vehicle_id=%s filename=%r content_type=%r",
        vehicle_id, file.filename, file.content_type,
    )

    raw_bytes = await file.read()
    logger.debug("CSV import: read %d bytes", len(raw_bytes))

    try:
        content = raw_bytes.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        logger.warning("CSV import failed: not UTF-8 (vehicle_id=%s)", vehicle_id)
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(content))

    if not reader.fieldnames:
        logger.warning("CSV import failed: empty file (vehicle_id=%s)", vehicle_id)
        raise HTTPException(status_code=400, detail="CSV file is empty.")

    logger.debug("CSV import: detected columns %s", list(reader.fieldnames))

    missing_cols = CSV_REQUIRED_COLS - set(reader.fieldnames)
    if missing_cols:
        logger.warning(
            "CSV import failed: missing columns %s (vehicle_id=%s)",
            sorted(missing_cols), vehicle_id,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(sorted(missing_cols))}",
        )

    entries_to_add = []
    row_errors: list[ImportRowError] = []

    for i, row in enumerate(reader, start=2):  # row 1 = header
        errors = []

        raw_date = row.get("Date", "").strip()
        performed_at = _parse_date(raw_date)
        if performed_at is None:
            errors.append(
                f"Invalid date {raw_date!r} (expected MM/DD/YYYY or YYYY-MM-DD)"
            )

        raw_odometer = row.get("Odometer", "").strip()
        odometer = _parse_odometer(raw_odometer)
        if odometer is None:
            errors.append(
                f"Invalid odometer {raw_odometer!r} (must be a number)"
            )

        title = row.get("Title", "").strip()
        if not title:
            errors.append("Title is required")

        if errors:
            logger.debug("CSV import: row %d failed validation: %s", i, errors)
            row_errors.append(ImportRowError(row=i, errors=errors))
            continue

        entries_to_add.append(
            MaintenanceEntry(
                vehicle_id=vehicle_id,
                title=title,
                performed_at=performed_at,
                odometer=odometer,
                shop_name=row.get("Shop", "").strip() or None,
                notes=row.get("Notes", "").strip() or None,
                cost=None,
            )
        )

    if row_errors:
        if not skip_errors:
            logger.warning(
                "CSV import aborted: %d row error(s) out of %d data row(s) (vehicle_id=%s)",
                len(row_errors), len(entries_to_add) + len(row_errors), vehicle_id,
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"{len(row_errors)} row(s) failed validation.",
                    "row_errors": [e.model_dump() for e in row_errors],
                },
            )
        logger.info(
            "CSV import: skipping %d invalid row(s), importing %d valid (vehicle_id=%s)",
            len(row_errors), len(entries_to_add), vehicle_id,
        )

    db.add_all(entries_to_add)
    await db.flush()
    logger.info(
        "CSV import complete: imported %d entries (vehicle_id=%s)",
        len(entries_to_add), vehicle_id,
    )

    return ImportResult(imported=len(entries_to_add), skipped=0)


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

    if payload.schedule_ids is not None:
        await db.refresh(entry, ["schedules"])
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