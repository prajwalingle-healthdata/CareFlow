-- CareFlow SQLite schema (synthetic data only).
-- Dates are stored as ISO-8601 text (YYYY-MM-DD). NULL means "not recorded in the source".
-- NULLs are deliberately preserved and never filled in: the app reports missing data instead of inventing it.

DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS procedures;
DROP TABLE IF EXISTS medications;
DROP TABLE IF EXISTS observations;
DROP TABLE IF EXISTS conditions;
DROP TABLE IF EXISTS encounters;
DROP TABLE IF EXISTS patients;

CREATE TABLE patients (
    patient_id     TEXT PRIMARY KEY,
    given_name     TEXT,
    family_name    TEXT,
    birth_date     TEXT,
    sex            TEXT,
    city           TEXT,
    language       TEXT,
    source_system  TEXT,
    synthetic      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE encounters (
    encounter_id   TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(patient_id),
    start_date     TEXT,
    end_date       TEXT,
    enc_class      TEXT,   -- inpatient | outpatient | emergency
    enc_type       TEXT,
    reason         TEXT,
    department     TEXT,
    status         TEXT,
    disposition    TEXT,
    source_system  TEXT,
    source_doc_id  TEXT
);

CREATE TABLE conditions (
    condition_id        TEXT PRIMARY KEY,
    patient_id          TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id        TEXT,
    display             TEXT,
    code                TEXT,
    code_system         TEXT,
    onset_date          TEXT,
    clinical_status     TEXT,
    verification_status TEXT,
    note                TEXT,
    source_system       TEXT,
    source_doc_id       TEXT
);

CREATE TABLE observations (
    observation_id TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id   TEXT,
    category       TEXT,   -- laboratory | vital-signs
    display        TEXT,
    code           TEXT,
    code_system    TEXT,
    value_num      REAL,
    value_text     TEXT,
    unit           TEXT,
    ref_low        REAL,
    ref_high       REAL,
    flag           TEXT,   -- flag exactly as supplied by the source system (H, L, ...)
    status         TEXT,
    effective_date TEXT,
    source_system  TEXT,
    source_doc_id  TEXT
);

CREATE TABLE medications (
    medication_id    TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id     TEXT,
    name             TEXT,
    dose             TEXT,
    route            TEXT,
    frequency        TEXT,
    status           TEXT,   -- active | completed | stopped
    start_date       TEXT,
    end_date         TEXT,
    indication       TEXT,
    last_reviewed    TEXT,
    note             TEXT,
    source_system    TEXT,
    source_doc_id    TEXT
);

CREATE TABLE procedures (
    procedure_id   TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id   TEXT,
    display        TEXT,
    code           TEXT,
    code_system    TEXT,
    performed_date TEXT,
    status         TEXT,
    note           TEXT,
    source_system  TEXT,
    source_doc_id  TEXT
);

CREATE TABLE documents (
    document_id    TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id   TEXT,
    doc_type       TEXT,   -- Laboratory report | Imaging report | Discharge summary | Clinical note | Operative note
    title          TEXT,
    doc_date       TEXT,
    author_role    TEXT,
    body           TEXT,
    source_system  TEXT
);

CREATE TABLE tasks (
    task_id        TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id   TEXT,
    description    TEXT,
    task_type      TEXT,   -- follow-up | investigation
    status         TEXT,   -- open | completed | NULL (not recorded)
    due_date       TEXT,
    documented_date TEXT,
    source_system  TEXT,
    source_doc_id  TEXT
);

CREATE INDEX idx_enc_patient  ON encounters(patient_id);
CREATE INDEX idx_obs_patient  ON observations(patient_id, code);
CREATE INDEX idx_cond_patient ON conditions(patient_id);
CREATE INDEX idx_med_patient  ON medications(patient_id);
CREATE INDEX idx_proc_patient ON procedures(patient_id);
CREATE INDEX idx_doc_patient  ON documents(patient_id);
CREATE INDEX idx_task_patient ON tasks(patient_id);
