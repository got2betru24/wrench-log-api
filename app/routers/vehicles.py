from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Vehicle, MaintenanceSchedule
from app.schemas.schemas import VehicleCreate, VehicleUpdate, VehicleOut, VehicleHealth
from app.services.health import compute_vehicle_health

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get("", response_model=list[VehicleOut])
async def list_vehicles(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
):
    q = select(Vehicle)
    if not include_archived:
        q = q.where(Vehicle.archived == False)
    q = q.order_by(Vehicle.name)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(payload: VehicleCreate, db: AsyncSession = Depends(get_db)):
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    await db.flush()
    await db.refresh(vehicle)
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.put("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: int, payload: VehicleUpdate, db: AsyncSession = Depends(get_db)
):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    await db.flush()
    await db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    await db.delete(vehicle)


@router.get("/{vehicle_id}/health", response_model=VehicleHealth)
async def vehicle_health(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    result = await db.execute(
        select(MaintenanceSchedule)
        .where(MaintenanceSchedule.vehicle_id == vehicle_id)
        .order_by(MaintenanceSchedule.sort_order)
    )
    schedules = result.scalars().all()
    return await compute_vehicle_health(db, vehicle, schedules)
