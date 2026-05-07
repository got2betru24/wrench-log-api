from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    Integer, SmallInteger, String, Text, Boolean,
    DateTime, Date, Numeric,
    ForeignKey, Index, func, Table, Column
)
from sqlalchemy.dialects.mysql import INTEGER as MYSQL_INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


# ─────────────────────────────────────────
# Association table: entry ↔ schedule (many-to-many)
# ─────────────────────────────────────────
entry_schedule_links = Table(
    "entry_schedule_links",
    Base.metadata,
    Column("entry_id",    MYSQL_INTEGER(unsigned=True), ForeignKey("maintenance_entries.id",   ondelete="CASCADE"), primary_key=True),
    Column("schedule_id", MYSQL_INTEGER(unsigned=True), ForeignKey("maintenance_schedules.id", ondelete="CASCADE"), primary_key=True),
)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id:            Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]            = mapped_column(String(100), nullable=False)
    make:          Mapped[str]            = mapped_column(String(50),  nullable=False)
    model:         Mapped[str]            = mapped_column(String(50),  nullable=False)
    year:          Mapped[int]            = mapped_column(SmallInteger, nullable=False)
    vin:           Mapped[str | None]     = mapped_column(String(17),  unique=True)
    color:         Mapped[str | None]     = mapped_column(String(30))
    license_plate: Mapped[str | None]     = mapped_column(String(20))
    notes:         Mapped[str | None]     = mapped_column(Text)
    archived:      Mapped[bool]           = mapped_column(Boolean, default=False)
    created_at:    Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())
    updated_at:    Mapped[datetime]       = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    schedules: Mapped[list["MaintenanceSchedule"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan", lazy="select"
    )
    entries: Mapped[list["MaintenanceEntry"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan", lazy="select",
        order_by="MaintenanceEntry.performed_at.desc()"
    )


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id:       Mapped[int]            = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    name:             Mapped[str]            = mapped_column(String(100), nullable=False)
    description:      Mapped[str | None]     = mapped_column(Text)
    interval_miles:   Mapped[int | None]     = mapped_column(Integer)
    interval_months:  Mapped[int | None]     = mapped_column(SmallInteger)
    estimated_cost:   Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    is_active:        Mapped[bool]           = mapped_column(Boolean, default=True)
    sort_order:       Mapped[int]            = mapped_column(SmallInteger, default=0)
    created_at:       Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped["Vehicle"] = relationship(back_populates="schedules")
    # back-reference so we can navigate schedule → entries if needed
    entries: Mapped[list["MaintenanceEntry"]] = relationship(
        secondary=entry_schedule_links, back_populates="schedules", lazy="select"
    )

    __table_args__ = (
        Index("idx_schedules_vehicle", "vehicle_id"),
    )


class MaintenanceEntry(Base):
    __tablename__ = "maintenance_entries"

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id:   Mapped[int]            = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)

    title:        Mapped[str]            = mapped_column(String(150), nullable=False)
    notes:        Mapped[str | None]     = mapped_column(Text)
    odometer:     Mapped[int | None]     = mapped_column(Integer)
    cost:         Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    shop_name:    Mapped[str | None]     = mapped_column(String(100))
    performed_at: Mapped[date]           = mapped_column(Date, nullable=False)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())
    updated_at:   Mapped[datetime]       = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    vehicle:     Mapped["Vehicle"] = relationship(back_populates="entries")
    attachments: Mapped[list["EntryAttachment"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    # Many-to-many: which schedule items were serviced by this entry
    schedules: Mapped[list["MaintenanceSchedule"]] = relationship(
        secondary=entry_schedule_links, back_populates="entries", lazy="select"
    )

    __table_args__ = (
        Index("idx_entries_vehicle_date", "vehicle_id", "performed_at"),
    )


class EntryAttachment(Base):
    __tablename__ = "entry_attachments"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id:    Mapped[int]      = mapped_column(ForeignKey("maintenance_entries.id", ondelete="CASCADE"), nullable=False)
    filename:    Mapped[str]      = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str]      = mapped_column(String(255), nullable=False)
    mime_type:   Mapped[str]      = mapped_column(String(100), nullable=False)
    file_size:   Mapped[int]      = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    entry: Mapped["MaintenanceEntry"] = relationship(back_populates="attachments")