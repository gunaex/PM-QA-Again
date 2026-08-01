import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# DATA_DIR is the parent folder holding both master.db and the projects/
# subfolder (one SQLite file, plus an evidence/ subfolder, per project).
# Defaults to backend/data for local dev — unset by default, so local
# `uvicorn` behaves exactly as before. Set it to override (e.g. a mounted
# volume when deployed).
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

MASTER_DB_URL = f"sqlite:///{os.path.join(DATA_DIR, 'master.db')}"

MasterBase = declarative_base()
ProjectBase = declarative_base()

master_engine = create_engine(
    MASTER_DB_URL, connect_args={"check_same_thread": False}
)
MasterSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=master_engine
)

_project_engines = {}
_project_sessions = {}

# Additive column patches, applied on top of `create_all` so pre-existing
# SQLite files (created before a schema patch) pick up new nullable columns
# without a full migration tool. Never used to change/remove existing columns
# — see ADR-0001 and the rebuild prompt section 2 for why this mirrors
# PM-Again's pattern exactly.
MASTER_COLUMN_PATCHES: dict[str, dict[str, str]] = {
    "projects": {
        "storage_quota_bytes": "INTEGER DEFAULT 5368709120",
        "storage_warning_thresholds": "TEXT DEFAULT '[70, 85, 95, 100]'",
    },
    # HYB-2: registration/heartbeat fields on an existing runner_tokens row.
    "runner_tokens": {
        "runner_name": "TEXT",
        "runner_version": "TEXT",
        "os_metadata": "TEXT",
        "browser_version": "TEXT",
        "capabilities_json": "TEXT",
        "last_heartbeat_at": "DATETIME",
    },
}
PROJECT_COLUMN_PATCHES: dict[str, dict[str, str]] = {
    # HYB-2: optional hybrid-evidence links on the existing evidence_items
    # table (docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md decision 2).
    "evidence_items": {
        "workflow_run_id": "INTEGER",
        "workflow_step_run_id": "INTEGER",
    },
}

# Additive index patches (docs/PERFORMANCE_FAST_PASS.md) — `CREATE INDEX
# IF NOT EXISTS` is safe against both a fresh database (created via
# `create_all`, which won't have these yet since the models don't declare
# them) and an existing one already missing them. Each entry names the
# query path it exists for, so future readers don't have to guess:
#   - cycle_test_results.cycle_id: every results-list/dashboard/report
#     query filters by cycle_id (was a full table scan per lookup).
#   - cycle_test_results.test_case_id: PASS-evidence and history joins.
#   - cycle_result_history.cycle_test_result_id: history panel + export.
#   - evidence_items.cycle_test_result_id: evidence gallery load,
#     PASS-evidence gate check, dashboard evidence-completeness.
#   - evidence_items.cycle_id: ZIP/Excel export evidence iteration.
#   - evidence_revisions.evidence_id: annotation history lookup.
#   - test_cases.revision_id: case list under a revision, cycle creation.
#   - test_cases.suite_id: suite case counts.
#   - script_revisions.suite_id: revision list under a suite.
#   - defects.cycle_id: dashboard open-defects-by-severity, go-live gate.
#   - sign_offs.cycle_id: sign-off summary report.
#   - activity_log.changed_at: dashboard "recent activity" ORDER BY DESC.
PROJECT_INDEXES: dict[str, list[str]] = {
    "cycle_test_results": ["cycle_id", "test_case_id"],
    "cycle_result_history": ["cycle_test_result_id"],
    "evidence_items": ["cycle_test_result_id", "cycle_id", "workflow_run_id"],
    "evidence_revisions": ["evidence_id"],
    "test_cases": ["revision_id", "suite_id"],
    "script_revisions": ["suite_id"],
    "defects": ["cycle_id"],
    "sign_offs": ["cycle_id"],
    "activity_log": ["changed_at"],
    # HYB-1: workflow list/editor lookups (workflow_revisions.workflow_id
    # for the revision-history list, workflow_steps.revision_id for the
    # ordered step list, workflow_test_case_links for both directions of
    # the case<->workflow link lookup).
    "workflow_revisions": ["workflow_id"],
    "workflow_steps": ["revision_id"],
    "workflow_test_case_links": ["workflow_revision_id", "test_case_id"],
    # HYB-2: run-list/claim/step-history/event lookups.
    "workflow_runs": ["workflow_revision_id", "status", "cycle_test_result_id"],
    "workflow_step_runs": ["workflow_run_id"],
    "runner_execution_events": ["workflow_run_id"],
    # HYB-3: recording-session claim/list and recorded-step ordering.
    "recording_sessions": ["workflow_id", "status"],
    "recorded_steps": ["recording_session_id"],
}


def ensure_columns(engine, table_columns: dict[str, dict[str, str]]):
    with engine.connect() as conn:
        for table, columns in table_columns.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, coltype in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))
        conn.commit()


def ensure_indexes(engine, table_columns: dict[str, list[str]]):
    with engine.connect() as conn:
        for table, columns in table_columns.items():
            for column in columns:
                index_name = f"ix_{table}_{column}"
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"))
        conn.commit()


def project_db_path(slug: str) -> str:
    return os.path.join(PROJECTS_DIR, f"{slug}.db")


def project_evidence_dir(slug: str) -> str:
    path = os.path.join(PROJECTS_DIR, slug, "evidence")
    os.makedirs(path, exist_ok=True)
    return path


def evidence_storage_root_dir() -> str:
    """Root for FilesystemEvidenceStorage (ADR-0002) — plain DATA_DIR, not
    DATA_DIR/evidence: object keys already start with `evidence/...`
    (`evidence/{slug}/{result_id}/...`) so the same key scheme works
    unchanged against R2 (see backend/app/storage/). Returning DATA_DIR
    here (rather than DATA_DIR/evidence) avoids a doubled `evidence/
    evidence/...` path on disk. Distinct from project_evidence_dir(),
    which is HYB-0's own spike-scoped evidence storage and is left
    untouched by this ADR."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def project_db_exists(slug: str) -> bool:
    return os.path.exists(project_db_path(slug))


def get_project_engine(slug: str):
    if slug not in _project_engines:
        url = f"sqlite:///{project_db_path(slug)}"
        # timeout=30: SQLite serializes writers — a concurrent evidence
        # upload's commit (see routers/evidence.py's quota race handling)
        # should wait for the other writer's commit rather than raising
        # "database is locked" under ordinary concurrency (Python's
        # sqlite3 default timeout is 5s, too tight for that).
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        ProjectBase.metadata.create_all(bind=engine)
        ensure_columns(engine, PROJECT_COLUMN_PATCHES)
        ensure_indexes(engine, PROJECT_INDEXES)
        _project_engines[slug] = engine
        _project_sessions[slug] = sessionmaker(
            autocommit=False, autoflush=False, bind=engine
        )
    return _project_engines[slug]


def open_project_session(slug: str):
    """Returns a new Session for `slug`, for use outside the FastAPI
    dependency-injection flow (e.g. from within another router's handler).
    Caller is responsible for closing it."""
    get_project_engine(slug)
    return _project_sessions[slug]()


def dispose_project_engine(slug: str) -> None:
    """Closes and drops the cached engine/sessionmaker for `slug` — required
    before deleting its SQLite file, otherwise a stale cached connection
    could still be used (or block the file delete on some platforms)."""
    engine = _project_engines.pop(slug, None)
    _project_sessions.pop(slug, None)
    if engine:
        engine.dispose()


def get_master_db():
    db = MasterSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_project_db(slug: str):
    """FastAPI dependency: `slug` is auto-resolved from the path parameter
    of the same name on the endpoint that depends on this."""
    get_project_engine(slug)
    session_local = _project_sessions[slug]
    db = session_local()
    try:
        yield db
    finally:
        db.close()
