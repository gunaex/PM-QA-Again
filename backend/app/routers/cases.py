import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..excel_utils import make_excel_response, make_template_response, read_import_excel, read_import_csv
from ..activity import log_changes
from ..auth import require_tester, require_project_access

router = APIRouter(
    prefix="/api/{slug}/revisions/{revision_id}/cases", tags=["test-cases"], dependencies=[Depends(require_project_access)]
)

# Matches the rebuild prompt's "Excel/CSV importer" required column set
# (section 11), but with PM-Again's strict-header validation instead of the
# original spec's user-mapping wizard — see ADR-0001 / rebuild prompt
# section 6 ("what to explicitly NOT carry forward").
COLUMNS = [
    "Test ID",
    "Title",
    "Priority",
    "Traceability",
    "Fixture",
    "Environment",
    "Preconditions / Setup",
    "Test Steps / Action",
    "Validation",
    "Expected Result",
    "Negative Path",
    "Mutation Level",
]


def _get_revision(db: Session, revision_id: int) -> models.ScriptRevision:
    revision = db.query(models.ScriptRevision).filter(models.ScriptRevision.id == revision_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


def _require_draft(revision: models.ScriptRevision):
    if revision.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Test cases can only be added/edited while the revision is DRAFT (current status: {revision.status})",
        )


def _content_hash(case_fields: dict) -> str:
    parts = [
        str(case_fields.get(k) or "")
        for k in ("title", "setup_md", "action_md", "validation_md", "expected_result_md", "traceability_md", "priority")
    ]
    return hashlib.sha256("␟".join(parts).encode("utf-8")).hexdigest()


@router.get("", response_model=list[schemas.TestCaseOut])
def list_cases(slug: str, revision_id: int, db: Session = Depends(get_project_db)):
    _get_revision(db, revision_id)
    return (
        db.query(models.TestCase)
        .filter(models.TestCase.revision_id == revision_id)
        .order_by(models.TestCase.sequence_no, models.TestCase.id)
        .all()
    )


@router.post("", response_model=schemas.TestCaseOut)
def create_case(
    slug: str,
    revision_id: int,
    payload: schemas.TestCaseCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, revision_id)
    _require_draft(revision)
    existing = (
        db.query(models.TestCase)
        .filter(models.TestCase.revision_id == revision_id, models.TestCase.checkpoint_code == payload.checkpoint_code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="A case with that checkpoint_code already exists in this revision")

    data = payload.model_dump()
    data["content_sha256"] = _content_hash(data)
    obj = models.TestCase(suite_id=revision.suite_id, revision_id=revision_id, **data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{case_id}", response_model=schemas.TestCaseOut)
def update_case(
    slug: str,
    revision_id: int,
    case_id: int,
    payload: schemas.TestCaseUpdate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, revision_id)
    _require_draft(revision)
    obj = db.query(models.TestCase).filter(models.TestCase.id == case_id, models.TestCase.revision_id == revision_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Test case not found")

    updates = payload.model_dump(exclude_unset=True)
    diffs = {k: (getattr(obj, k), v) for k, v in updates.items() if getattr(obj, k) != v}
    for key, value in updates.items():
        setattr(obj, key, value)
    obj.content_sha256 = _content_hash({c.name: getattr(obj, c.name) for c in models.TestCase.__table__.columns})
    log_changes(db, "test_case", case_id, diffs, user.email)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{case_id}")
def delete_case(
    slug: str,
    revision_id: int,
    case_id: int,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, revision_id)
    _require_draft(revision)
    obj = db.query(models.TestCase).filter(models.TestCase.id == case_id, models.TestCase.revision_id == revision_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Test case not found")
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/export")
def export_cases(slug: str, revision_id: int, db: Session = Depends(get_project_db)):
    _get_revision(db, revision_id)
    items = (
        db.query(models.TestCase)
        .filter(models.TestCase.revision_id == revision_id)
        .order_by(models.TestCase.sequence_no, models.TestCase.id)
        .all()
    )
    rows = [
        {
            "Test ID": item.checkpoint_code,
            "Title": item.title,
            "Priority": item.priority,
            "Traceability": item.traceability_md,
            "Fixture": item.fixture_md,
            "Environment": item.environment_md,
            "Preconditions / Setup": item.setup_md,
            "Test Steps / Action": item.action_md,
            "Validation": item.validation_md,
            "Expected Result": item.expected_result_md,
            "Negative Path": item.negative_path,
            "Mutation Level": item.mutation_level,
        }
        for item in items
    ]
    return make_excel_response(rows, COLUMNS, f"{slug}-revision-{revision_id}-cases.xlsx")


@router.get("/import-template")
def import_template():
    return make_template_response(COLUMNS, "test-cases-import-template.xlsx")


def _apply_import_records(db: Session, revision: models.ScriptRevision, records: list[dict], source_type: str, filename: Optional[str]):
    max_seq = (
        db.query(models.TestCase.sequence_no)
        .filter(models.TestCase.revision_id == revision.id)
        .order_by(models.TestCase.sequence_no.desc())
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1

    existing_codes = {
        row[0]
        for row in db.query(models.TestCase.checkpoint_code).filter(models.TestCase.revision_id == revision.id).all()
    }
    seen_in_file = set()
    duplicates_in_file = []
    duplicates_existing = []
    created = 0

    for record in records:
        checkpoint_code = (record.get("Test ID") or "").strip() if record.get("Test ID") else None
        if not checkpoint_code or not record.get("Title") or not record.get("Test Steps / Action") or not record.get("Expected Result"):
            continue  # incomplete row — skipped, not silently invented
        if checkpoint_code in seen_in_file:
            duplicates_in_file.append(checkpoint_code)
            continue
        if checkpoint_code in existing_codes:
            duplicates_existing.append(checkpoint_code)
            continue
        seen_in_file.add(checkpoint_code)

        negative_path = record.get("Negative Path")
        if isinstance(negative_path, str):
            negative_path = negative_path.strip().lower() in ("true", "1", "yes", "y")
        else:
            negative_path = bool(negative_path)

        mutation_level = (record.get("Mutation Level") or "UNSPECIFIED").strip().upper() or "UNSPECIFIED"
        if mutation_level not in models.MUTATION_LEVELS:
            mutation_level = "UNSPECIFIED"

        fields = {
            "checkpoint_code": checkpoint_code,
            "title": record.get("Title"),
            "priority": record.get("Priority"),
            "traceability_md": record.get("Traceability"),
            "fixture_md": record.get("Fixture"),
            "environment_md": record.get("Environment"),
            "setup_md": record.get("Preconditions / Setup"),
            "action_md": record.get("Test Steps / Action"),
            "validation_md": record.get("Validation"),
            "expected_result_md": record.get("Expected Result"),
            "negative_path": negative_path,
            "mutation_level": mutation_level,
            "sequence_no": next_seq,
        }
        fields["content_sha256"] = _content_hash(fields)
        db.add(models.TestCase(suite_id=revision.suite_id, revision_id=revision.id, **fields))
        next_seq += 1
        created += 1

    revision.source_type = source_type
    revision.source_filename = filename
    db.commit()

    return {
        "imported": created,
        "duplicate_in_file": duplicates_in_file,
        "duplicate_existing": duplicates_existing,
    }


@router.post("/import-excel")
async def import_cases_excel(
    slug: str,
    revision_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, revision_id)
    _require_draft(revision)
    content = await file.read()
    records = read_import_excel(content, COLUMNS)
    return _apply_import_records(db, revision, records, "XLSX", file.filename)


@router.post("/import-csv")
async def import_cases_csv(
    slug: str,
    revision_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, revision_id)
    _require_draft(revision)
    content = await file.read()
    records = read_import_csv(content, COLUMNS)
    return _apply_import_records(db, revision, records, "CSV", file.filename)
