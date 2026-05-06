# WrenchLog — Backend

FastAPI backend providing the REST API, health score engine, and file upload handling for WrenchLog.

---

## Structure

```
backend/
├── .env.example
├── requirements.txt
└── app/
    ├── main.py                 # App factory, CORS, lifespan (table creation)
    ├── core/
    │   ├── config.py           # Pydantic settings — all config via environment variables
    │   └── database.py         # Async SQLAlchemy engine, session factory, Base
    ├── models/
    │   └── models.py           # ORM: Vehicle, MaintenanceSchedule, MaintenanceEntry, EntryAttachment
    ├── schemas/
    │   └── schemas.py          # Pydantic I/O schemas + VehicleHealth, DashboardSummary
    ├── services/
    │   └── health.py           # Health score engine, mileage projection, upcoming item detection
    └── routers/
        ├── vehicles.py         # CRUD + /health endpoint
        ├── schedules.py        # CRUD + /seed-templates
        ├── entries.py          # CRUD + file upload/download/delete + mileage history
        └── dashboard.py        # Aggregate fleet summary
```

---

## Setup

```bash
cd backend
cp .env.example .env
# Edit .env — at minimum set DB_PASSWORD

pip install -r requirements.txt

# Development
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Tables are created automatically on first startup via `Base.metadata.create_all`. For production schema changes, add Alembic.

---

## Environment Variables

| Variable        | Default              | Required | Description                          |
|-----------------|----------------------|----------|--------------------------------------|
| `DB_HOST`       | `localhost`          |          | MySQL hostname                       |
| `DB_PORT`       | `3306`               |          | MySQL port                           |
| `DB_NAME`       | `auto_maintenance`   |          | Database name                        |
| `DB_USER`       | `root`               |          | Database user                        |
| `DB_PASSWORD`   | —                    | ✓        | Database password                    |
| `UPLOAD_DIR`    | `/uploads`           |          | Filesystem path for file attachments |
| `MAX_UPLOAD_MB` | `20`                 |          | Max upload size in megabytes         |
| `CORS_ORIGINS`  | `["http://localhost:5173"]` |   | Allowed CORS origins (JSON array)    |
| `DEBUG`         | `false`              |          | Enables SQLAlchemy query logging     |

---

## API Reference

All routes are prefixed with `/api`.

### Vehicles

| Method | Path                            | Description                          |
|--------|---------------------------------|--------------------------------------|
| GET    | `/vehicles`                     | List vehicles (`?include_archived=`) |
| POST   | `/vehicles`                     | Create vehicle                       |
| GET    | `/vehicles/{id}`                | Get vehicle                          |
| PUT    | `/vehicles/{id}`                | Update vehicle (partial)             |
| DELETE | `/vehicles/{id}`                | Delete vehicle (cascades all data)   |
| GET    | `/vehicles/{id}/health`         | Health score, upcoming items, stats  |

### Maintenance Schedules

| Method | Path                                       | Description                          |
|--------|--------------------------------------------|--------------------------------------|
| GET    | `/vehicles/{id}/schedules`                 | List schedule items                  |
| POST   | `/vehicles/{id}/schedules`                 | Create schedule item                 |
| POST   | `/vehicles/{id}/schedules/seed-templates`  | Seed 10 common items                 |
| PUT    | `/vehicles/{id}/schedules/{sid}`           | Update schedule item                 |
| DELETE | `/vehicles/{id}/schedules/{sid}`           | Delete schedule item                 |

### Maintenance Entries

| Method | Path                              | Description                          |
|--------|-----------------------------------|--------------------------------------|
| GET    | `/vehicles/{id}/entries`          | List entries (`?limit=&offset=`)     |
| POST   | `/vehicles/{id}/entries`          | Log maintenance entry                |
| GET    | `/entries/{id}`                   | Get single entry                     |
| PUT    | `/entries/{id}`                   | Update entry (partial)               |
| DELETE | `/entries/{id}`                   | Delete entry                         |
| GET    | `/vehicles/{id}/mileage`          | Odometer history for chart           |
| POST   | `/entries/{id}/attachments`       | Upload file (JPEG/PNG/WebP/GIF/PDF)  |
| GET    | `/attachments/{id}/file`          | Download/serve attachment            |
| DELETE | `/attachments/{id}`               | Delete attachment + file on disk     |

### Dashboard

| Method | Path         | Description                                  |
|--------|--------------|----------------------------------------------|
| GET    | `/dashboard` | Fleet totals, per-vehicle health, all alerts |

---

## Health Score Engine (`services/health.py`)

The health score is computed on-demand per request — nothing is stored in the DB.

**Scoring:**
- Starts at 100
- −20 per overdue scheduled item
- −8 per due-soon item
- −10 if no service logged in over 1 year
- Clamped to 0–100

**Status thresholds:**
- `overdue` — miles_until_due ≤ 0 OR days_until_due ≤ 0
- `due_soon` — miles_until_due ≤ 500 OR days_until_due ≤ 14
- `ok` — everything else

**Mileage projection:**
Daily mileage rate is estimated from the oldest and newest odometer readings. This rate is used to project a calendar date for the next mileage-based service interval.

---

## Seed Templates

`POST /api/vehicles/{id}/schedules/seed-templates` inserts these 10 items:

| Item                | Miles    | Months |
|---------------------|----------|--------|
| Oil Change          | 5,000    | 6      |
| Tire Rotation       | 7,500    | 6      |
| Air Filter          | 15,000   | 12     |
| Cabin Air Filter    | 15,000   | 12     |
| Brake Inspection    | 20,000   | 12     |
| Transmission Fluid  | 30,000   | 24     |
| Coolant Flush       | 30,000   | 24     |
| Spark Plugs         | 30,000   | —      |
| Timing Belt         | 60,000   | —      |
| Wheel Alignment     | —        | 12     |

---

## File Uploads

- Accepted types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `application/pdf`
- Max size: configurable via `MAX_UPLOAD_MB` (default 20 MB)
- Stored as UUID-named files at `UPLOAD_DIR/{uuid}{ext}`
- Original filename preserved in the `entry_attachments` table
- Deleting an attachment also removes the file from disk

---

## Docker Notes

Recommended container config:

```yaml
image: python:3.13-slim
command: uvicorn app.main:app --host 0.0.0.0 --port 8000
working_dir: /app
volumes:
  - ./backend:/app
  - uploads_volume:/uploads
environment:
  - DB_HOST=your_mysql_host
  - DB_PASSWORD=your_password
  - UPLOAD_DIR=/uploads
  - CORS_ORIGINS=["https://yourdomain.com"]
```
