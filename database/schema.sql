-- Auto Maintenance Tracker - Database Schema
-- MySQL 8.0

CREATE DATABASE IF NOT EXISTS wrench_log CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE wrench_log;

-- ─────────────────────────────────────────
-- Vehicles
-- ─────────────────────────────────────────
CREATE TABLE vehicles (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100)  NOT NULL COMMENT 'Friendly name, e.g. "Daily Driver"',
    make          VARCHAR(50)   NOT NULL,
    model         VARCHAR(50)   NOT NULL,
    year          SMALLINT UNSIGNED NOT NULL,
    vin           VARCHAR(17)   NULL UNIQUE,
    color         VARCHAR(30)   NULL,
    license_plate VARCHAR(20)   NULL,
    notes         TEXT          NULL,
    archived      TINYINT(1)    NOT NULL DEFAULT 0,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- Maintenance Schedules (recurring items per vehicle)
-- ─────────────────────────────────────────
CREATE TABLE maintenance_schedules (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    vehicle_id       INT UNSIGNED NOT NULL,
    name             VARCHAR(100) NOT NULL COMMENT 'e.g. "Oil Change", "Tire Rotation"',
    description      TEXT         NULL,
    interval_miles   INT UNSIGNED NULL COMMENT 'Repeat every N miles',
    interval_months  TINYINT UNSIGNED NULL COMMENT 'Repeat every N months',
    estimated_cost   DECIMAL(8,2) NULL,
    is_active        TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order       SMALLINT     NOT NULL DEFAULT 0,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_schedule_vehicle FOREIGN KEY (vehicle_id)
        REFERENCES vehicles(id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────
-- Maintenance Entries (log of work done)
-- ─────────────────────────────────────────
CREATE TABLE maintenance_entries (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    vehicle_id   INT UNSIGNED  NOT NULL,
    title        VARCHAR(150)  NOT NULL,
    notes        TEXT          NULL,
    odometer     INT UNSIGNED  NULL COMMENT 'Miles at time of service',
    cost         DECIMAL(8,2)  NULL,
    shop_name    VARCHAR(100)  NULL,
    performed_at DATE          NOT NULL,
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_entry_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────
-- Entry ↔ Schedule links (many-to-many)
-- One service visit can cover multiple schedule items
-- ─────────────────────────────────────────
CREATE TABLE entry_schedule_links (
    entry_id    INT UNSIGNED NOT NULL,
    schedule_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (entry_id, schedule_id),
    CONSTRAINT fk_esl_entry    FOREIGN KEY (entry_id)    REFERENCES maintenance_entries(id)    ON DELETE CASCADE,
    CONSTRAINT fk_esl_schedule FOREIGN KEY (schedule_id) REFERENCES maintenance_schedules(id)  ON DELETE CASCADE
);

-- ─────────────────────────────────────────
-- Entry Attachments (receipts, inspection reports)
-- ─────────────────────────────────────────
CREATE TABLE entry_attachments (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    entry_id     INT UNSIGNED  NOT NULL,
    filename     VARCHAR(255)  NOT NULL COMMENT 'Original filename',
    stored_name  VARCHAR(255)  NOT NULL COMMENT 'UUID filename on disk',
    mime_type    VARCHAR(100)  NOT NULL,
    file_size    INT UNSIGNED  NOT NULL COMMENT 'Bytes',
    uploaded_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_attachment_entry FOREIGN KEY (entry_id)
        REFERENCES maintenance_entries(id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────
CREATE INDEX idx_entries_vehicle_date ON maintenance_entries (vehicle_id, performed_at DESC);
CREATE INDEX idx_schedules_vehicle    ON maintenance_schedules (vehicle_id);
CREATE INDEX idx_esl_schedule         ON entry_schedule_links (schedule_id);
