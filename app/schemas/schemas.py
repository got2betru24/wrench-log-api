from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


# ─────────────────────────────────────────
# Shared / Base
# ─────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────
# Vehicle
# ─────────────────────────────────────────

class VehicleCreate(BaseModel):
    name: str
    make: str
    model: str
    year: int
    vin: Optional[str] = None
    color: Optional[str] = None
    license_plate: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("year")
    @classmethod
    def valid_year(cls, v: int) -> int:
        if not (1900 <= v <= 2100):
            raise ValueError("Year must be between 1900 and 2100")
        return v


class VehicleUpdate(BaseModel):
    name: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    license_plate: Optional[str] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None


class VehicleOut(OrmBase):
    id: int
    name: str
    make: str
    model: str
    year: int
    vin: Optional[str]
    color: Optional[str]
    license_plate: Optional[str]
    notes: Optional[str]
    archived: bool
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────
# Maintenance Schedule
# ─────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    interval_miles: Optional[int] = None
    interval_months: Optional[int] = None
    estimated_cost: Optional[Decimal] = None
    is_active: bool = True
    sort_order: int = 0


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    interval_miles: Optional[int] = None
    interval_months: Optional[int] = None
    estimated_cost: Optional[Decimal] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class ScheduleOut(OrmBase):
    id: int
    vehicle_id: int
    name: str
    description: Optional[str]
    interval_miles: Optional[int]
    interval_months: Optional[int]
    estimated_cost: Optional[Decimal]
    is_active: bool
    sort_order: int
    created_at: datetime


# ─────────────────────────────────────────
# Maintenance Entry
# ─────────────────────────────────────────

class EntryCreate(BaseModel):
    schedule_id: Optional[int] = None
    title: str
    notes: Optional[str] = None
    odometer: Optional[int] = None
    cost: Optional[Decimal] = None
    shop_name: Optional[str] = None
    performed_at: date


class EntryUpdate(BaseModel):
    schedule_id: Optional[int] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    odometer: Optional[int] = None
    cost: Optional[Decimal] = None
    shop_name: Optional[str] = None
    performed_at: Optional[date] = None


class AttachmentOut(OrmBase):
    id: int
    entry_id: int
    filename: str
    stored_name: str
    mime_type: str
    file_size: int
    uploaded_at: datetime


class EntryOut(OrmBase):
    id: int
    vehicle_id: int
    schedule_id: Optional[int]
    title: str
    notes: Optional[str]
    odometer: Optional[int]
    cost: Optional[Decimal]
    shop_name: Optional[str]
    performed_at: date
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut] = []


# ─────────────────────────────────────────
# Health / Dashboard
# ─────────────────────────────────────────

class UpcomingItem(BaseModel):
    schedule_id: int
    schedule_name: str
    vehicle_id: int
    vehicle_name: str
    status: str          # "overdue" | "due_soon" | "ok"
    last_odometer: Optional[int]
    last_performed: Optional[date]
    next_due_miles: Optional[int]
    next_due_date: Optional[date]
    miles_until_due: Optional[int]
    days_until_due: Optional[int]


class VehicleHealth(BaseModel):
    vehicle_id: int
    score: int           # 0–100
    label: str           # "Good" | "Fair" | "Attention Needed"
    color: str           # "success" | "warning" | "error"
    overdue_count: int
    due_soon_count: int
    upcoming_items: list[UpcomingItem]
    last_entry_date: Optional[date]
    total_cost_ytd: Optional[Decimal]
    estimated_daily_miles: Optional[float]


class MileagePoint(BaseModel):
    performed_at: date
    odometer: int


class DashboardSummary(BaseModel):
    total_vehicles: int
    overdue_count: int
    due_soon_count: int
    total_cost_ytd: Decimal
    vehicles_health: list[VehicleHealth]
