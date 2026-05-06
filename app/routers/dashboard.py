from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Vehicle, MaintenanceSchedule
from app.schemas.schemas import DashboardSummary
from app.services.health import compute_vehicle_health

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("", response_model=DashboardSummary)
async def dashboard(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Vehicle).where(Vehicle.archived == False).order_by(Vehicle.name)
    )
    vehicles = result.scalars().all()

    all_health = []
    for vehicle in vehicles:
        sched_result = await db.execute(
            select(MaintenanceSchedule)
            .where(MaintenanceSchedule.vehicle_id == vehicle.id)
            .order_by(MaintenanceSchedule.sort_order)
        )
        schedules = sched_result.scalars().all()
        health = await compute_vehicle_health(db, vehicle, schedules)
        all_health.append(health)

    total_overdue = sum(h.overdue_count for h in all_health)
    total_due_soon = sum(h.due_soon_count for h in all_health)
    total_cost = sum(h.total_cost_ytd or Decimal("0") for h in all_health)

    return DashboardSummary(
        total_vehicles=len(vehicles),
        overdue_count=total_overdue,
        due_soon_count=total_due_soon,
        total_cost_ytd=total_cost,
        vehicles_health=all_health,
    )
