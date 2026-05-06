from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Vehicle, MaintenanceSchedule
from app.schemas.schemas import ScheduleCreate, ScheduleUpdate, ScheduleOut

router = APIRouter(prefix="/vehicles/{vehicle_id}/schedules", tags=["Schedules"])

COMMON_TEMPLATES = [
    {"name": "Oil Change",         "interval_miles": 5000,  "interval_months": 6},
    {"name": "Tire Rotation",      "interval_miles": 7500,  "interval_months": 6},
    {"name": "Air Filter",         "interval_miles": 15000, "interval_months": 12},
    {"name": "Cabin Air Filter",   "interval_miles": 15000, "interval_months": 12},
    {"name": "Brake Inspection",   "interval_miles": 20000, "interval_months": 12},
    {"name": "Transmission Fluid", "interval_miles": 30000, "interval_months": 24},
    {"name": "Coolant Flush",      "interval_miles": 30000, "interval_months": 24},
    {"name": "Spark Plugs",        "interval_miles": 30000, "interval_months": None},
    {"name": "Timing Belt",        "interval_miles": 60000, "interval_months": None},
    {"name": "Wheel Alignment",    "interval_miles": None,  "interval_months": 12},
]


async def _get_vehicle_or_404(vehicle_id: int, db: AsyncSession) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    await _get_vehicle_or_404(vehicle_id, db)
    result = await db.execute(
        select(MaintenanceSchedule)
        .where(MaintenanceSchedule.vehicle_id == vehicle_id)
        .order_by(MaintenanceSchedule.sort_order, MaintenanceSchedule.name)
    )
    return result.scalars().all()


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    vehicle_id: int, payload: ScheduleCreate, db: AsyncSession = Depends(get_db)
):
    await _get_vehicle_or_404(vehicle_id, db)
    sched = MaintenanceSchedule(vehicle_id=vehicle_id, **payload.model_dump())
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


@router.post("/seed-templates", response_model=list[ScheduleOut], status_code=status.HTTP_201_CREATED)
async def seed_templates(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    """Seed a vehicle's schedule with common maintenance items."""
    await _get_vehicle_or_404(vehicle_id, db)
    created = []
    for i, tmpl in enumerate(COMMON_TEMPLATES):
        sched = MaintenanceSchedule(
            vehicle_id=vehicle_id,
            sort_order=i,
            **tmpl,
        )
        db.add(sched)
        created.append(sched)
    await db.flush()
    for s in created:
        await db.refresh(s)
    return created


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    vehicle_id: int,
    schedule_id: int,
    payload: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    sched = await db.get(MaintenanceSchedule, schedule_id)
    if not sched or sched.vehicle_id != vehicle_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(sched, field, value)
    await db.flush()
    await db.refresh(sched)
    return sched


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    vehicle_id: int, schedule_id: int, db: AsyncSession = Depends(get_db)
):
    sched = await db.get(MaintenanceSchedule, schedule_id)
    if not sched or sched.vehicle_id != vehicle_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(sched)
