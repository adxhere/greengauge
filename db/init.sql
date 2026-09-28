-- GreenGauge database schema (runs automatically the first time the db container starts)

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Main plant meter: one row per minute
CREATE TABLE IF NOT EXISTS incomer_readings (
    time          TIMESTAMPTZ      NOT NULL,
    plant_id      TEXT             NOT NULL,
    device        TEXT             NOT NULL,
    kw            REAL,
    kvar          REAL,
    kva           REAL,
    pf            REAL,
    voltage       REAL,
    ia            REAL,
    ib            REAL,
    ic            REAL,
    energy_kwh    DOUBLE PRECISION,   -- cumulative meter register
    pieces_total  INTEGER,            -- cumulative production counter
    ambient_c     REAL,
    shift         TEXT,
    producing     BOOLEAN,
    PRIMARY KEY (plant_id, device, time)
);
SELECT create_hypertable('incomer_readings', 'time', if_not_exists => TRUE);

-- Clamp-on CT meters on each machine: one row per machine per minute
CREATE TABLE IF NOT EXISTS machine_readings (
    time          TIMESTAMPTZ      NOT NULL,
    plant_id      TEXT             NOT NULL,
    device        TEXT             NOT NULL,
    kw            REAL,
    kvar          REAL,
    kva           REAL,
    pf            REAL,
    voltage       REAL,
    ia            REAL,
    ib            REAL,
    ic            REAL,
    energy_kwh    DOUBLE PRECISION,
    status        TEXT,               -- off / idle / running
    loaded_s      SMALLINT,           -- compressor: seconds loaded in the minute
    PRIMARY KEY (plant_id, device, time)
);
SELECT create_hypertable('machine_readings', 'time', if_not_exists => TRUE);

-- Handy view: pieces produced per minute (difference of the cumulative counter)
CREATE OR REPLACE VIEW incomer_with_pieces AS
SELECT *,
       GREATEST(pieces_total - LAG(pieces_total) OVER (PARTITION BY plant_id ORDER BY time), 0) AS pieces
FROM incomer_readings;
