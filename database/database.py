"""SQLite access layer for CareFlow.

The database file is created locally on first run from the synthetic generator.
`reset_database()` deletes and regenerates it, restoring the original demonstration dataset.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from utils.synthetic_data import TABLES, generate_dataset, write_json

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "careflow.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
JSON_PATH = DATA_DIR / "synthetic_patients.json"
FHIR_SAMPLE_PATH = DATA_DIR / "sample_fhir.json"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    dataset = generate_dataset()
    for table in TABLES:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        conn.executemany(sql, [tuple(row.get(c) for c in cols) for row in dataset[table]])
    conn.commit()


def init_db(db_path: Path | str | None = None, reset: bool = False) -> None:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and path.exists():
        path.unlink()
    if not path.exists():
        with get_connection(path) as conn:
            _seed(conn)
        _write_data_files(path)


def reset_database(db_path: Path | str | None = None) -> dict:
    """Delete and regenerate the demonstration dataset. Returns record counts."""
    init_db(db_path, reset=True)
    return table_counts(db_path)


def table_counts(db_path: Path | str | None = None) -> dict:
    with get_connection(db_path) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def _write_data_files(db_path: Path) -> None:
    """Write data/synthetic_patients.json and data/sample_fhir.json (only for the default database)."""
    if Path(db_path) != DB_PATH:
        return
    from utils.fhir_mapping import build_bundle
    write_json(JSON_PATH)
    FHIR_SAMPLE_PATH.write_text(json.dumps(build_bundle(load_patient_bundle("SYN-0001", db_path)), indent=2), encoding="utf-8")


def read_table(table: str, patient_id: str | None = None, db_path: Path | str | None = None) -> pd.DataFrame:
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    with get_connection(db_path) as conn:
        if patient_id:
            return pd.read_sql_query(f"SELECT * FROM {table} WHERE patient_id = ?", conn, params=(patient_id,))
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


def list_patients(db_path: Path | str | None = None) -> pd.DataFrame:
    return read_table("patients", db_path=db_path)


def load_patient_bundle(patient_id: str, db_path: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """All records for one patient, as a dict of DataFrames keyed by table name."""
    return {t: read_table(t, patient_id, db_path) for t in TABLES}
