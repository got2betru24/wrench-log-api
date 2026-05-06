from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.models import Vehicle, MaintenanceSchedule, MaintenanceEntry
from app.schemas.schemas import VehicleHealth, UpcomingItem, MileagePoint


async def get_last_entry_for_schedule(
    db: AsyncSession, vehicle_id: int, schedule_id: int
) -> Optional[MaintenanceEntry]:
    result = await db.execute(
        select(MaintenanceEntry)
        .where(
            MaintenanceEntry.vehicle_id == vehicle_id,
            MaintenanceEntry.schedule_id == schedule_id,
        )
        .order_by(MaintenanceEntry.performed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_odometer(db: AsyncSession, vehicle_id: int) -> Optional[int]:
    result = await db.execute(
        select(MaintenanceEntry.odometer)
        .where(
            MaintenanceEntry.vehicle_id == vehicle_id,
            MaintenanceEntry.odometer.is_not(None),
        )
        .order_by(MaintenanceEntry.performed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_mileage_history(
    db: AsyncSession, vehicle_id: int
) -> list[MileagePoint]:
    result = await db.execute(
        select(MaintenanceEntry.performed_at, MaintenanceEntry.odometer)
        .where(
            MaintenanceEntry.vehicle_id == vehicle_id,
            MaintenanceEntry.odometer.is_not(None),
        )
        .order_by(MaintenanceEntry.performed_at.asc())
    )
    rows = result.all()
    return [MileagePoint(performed_at=r.performed_at, odometer=r.odometer) for r in rows]


def estimate_daily_miles(history: list[MileagePoint]) -> Optional[float]:
    """Linear estimate of miles per day from odometer history."""
    if len(history) < 2:
        return None
    oldest = history[0]
    newest = history[-1]
    days = (newest.performed_at - oldest.performed_at).days
    if days <= 0:
        return None
    return (newest.odometer - oldest.odometer) / days


async def compute_vehicle_health(
    db: AsyncSession,
    vehicle: Vehicle,
    schedules: list[MaintenanceSchedule],
) -> VehicleHealth:
    today = date.today()
    mileage_history = await get_mileage_history(db, vehicle.id)
    daily_miles = estimate_daily_miles(mileage_history)
    current_odo = await get_latest_odometer(db, vehicle.id)

    # YTD cost
    ytd_result = await db.execute(
        select(func.sum(MaintenanceEntry.cost)).where(
            MaintenanceEntry.vehicle_id == vehicle.id,
            func.year(MaintenanceEntry.performed_at) == today.year,
        )
    )
    total_cost_ytd: Decimal = ytd_result.scalar_one_or_none() or Decimal("0.00")

    # Last entry date
    last_result = await db.execute(
        select(MaintenanceEntry.performed_at)
        .where(MaintenanceEntry.vehicle_id == vehicle.id)
        .order_by(MaintenanceEntry.performed_at.desc())
        .limit(1)
    )
    last_entry_date = last_result.scalar_one_or_none()

    upcoming_items: list[UpcomingItem] = []

    for sched in schedules:
        if not sched.is_active:
            continue

        last = await get_last_entry_for_schedule(db, vehicle.id, sched.id)
        last_odo = last.odometer if last and last.odometer else None
        last_date = last.performed_at if last else None

        # Compute next due
        next_due_miles: Optional[int] = None
        next_due_date: Optional[date] = None
        miles_until_due: Optional[int] = None
        days_until_due: Optional[int] = None

        if sched.interval_miles and last_odo is not None:
            next_due_miles = last_odo + sched.interval_miles
            if current_odo is not None:
                miles_until_due = next_due_miles - current_odo
                if daily_miles and daily_miles > 0:
                    eta_days = miles_until_due / daily_miles
                    next_due_date = today + timedelta(days=int(eta_days))
                    days_until_due = int(eta_days)
        elif sched.interval_miles and last_odo is None and current_odo is not None:
            next_due_miles = current_odo + sched.interval_miles

        if sched.interval_months and last_date:
            # months approximated as 30.44 days
            due = last_date + timedelta(days=int(sched.interval_months * 30.44))
            if next_due_date is None:
                next_due_date = due
            days_until_due = (due - today).days

        # Determine status
        overdue = False
        due_soon = False

        if miles_until_due is not None:
            if miles_until_due <= 0:
                overdue = True
            elif miles_until_due <= 500:
                due_soon = True

        if days_until_due is not None:
            if days_until_due <= 0:
                overdue = True
            elif days_until_due <= 14 and not overdue:
                due_soon = True

        if overdue:
            status = "overdue"
        elif due_soon:
            status = "due_soon"
        else:
            status = "ok"

        upcoming_items.append(UpcomingItem(
            schedule_id=sched.id,
            schedule_name=sched.name,
            vehicle_id=vehicle.id,
            vehicle_name=vehicle.name,
            status=status,
            last_odometer=last_odo,
            last_performed=last_date,
            next_due_miles=next_due_miles,
            next_due_date=next_due_date,
            miles_until_due=miles_until_due,
            days_until_due=days_until_due,
        ))

    # Sort: overdue first, then due_soon, then ok
    status_order = {"overdue": 0, "due_soon": 1, "ok": 2}
    upcoming_items.sort(key=lambda x: status_order[x.status])

    overdue_count = sum(1 for i in upcoming_items if i.status == "overdue")
    due_soon_count = sum(1 for i in upcoming_items if i.status == "due_soon")

    # Score: start at 100, penalize
    score = 100
    score -= overdue_count * 20
    score -= due_soon_count * 8
    if last_entry_date:
        days_since = (today - last_entry_date).days
        if days_since > 365:
            score -= 10
    score = max(0, min(100, score))

    if score >= 80:
        label, color = "Good", "success"
    elif score >= 50:
        label, color = "Fair", "warning"
    else:
        label, color = "Attention Needed", "error"

    return VehicleHealth(
        vehicle_id=vehicle.id,
        score=score,
        label=label,
        color=color,
        overdue_count=overdue_count,
        due_soon_count=due_soon_count,
        upcoming_items=upcoming_items,
        last_entry_date=last_entry_date,
        total_cost_ytd=total_cost_ytd,
        estimated_daily_miles=daily_miles,
    )
