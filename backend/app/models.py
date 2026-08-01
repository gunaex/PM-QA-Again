from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint

from .database import MasterBase, ProjectBase

# QA-Again's own roles (kept from the original spec — see ADR-0001 section 2
# for why this is a global column on `users`, not a per-project table).
ROLES = ("ADMIN", "TESTER", "VIEWER")


class Project(MasterBase):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    # Optional one-way link to the matching PM-Again project — see rebuild
    # prompt section 8. No shared DB/auth/sync, just a "back to PM-Again" URL.
    external_project_url = Column(String, nullable=True)
    archived = Column(Boolean, default=False)
    # Evidence storage quota (ADR-0002) — 5 GiB default, admin-adjustable
    # per project. Thresholds stored as a JSON array string, e.g.
    # "[70, 85, 95, 100]"; kept configurable per project rather than a
    # global constant per requirement 9.
    storage_quota_bytes = Column(Integer, default=5 * 1024 * 1024 * 1024)
    storage_warning_thresholds = Column(String, default="[70, 85, 95, 100]")
    created_at = Column(DateTime, default=datetime.utcnow)


class User(MasterBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # ADMIN | TESTER | VIEWER
    active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RefreshToken(MasterBase):
    """Opaque refresh tokens, stored hashed (never the raw token) so a DB
    leak alone doesn't hand out working credentials. Revocable on logout."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Per-project QA domain models ----------
# Live in each project's own SQLite file (ProjectBase) — see database.py's
# get_project_engine. No project_id column needed, unlike the original
# spec's shared-D1 schema: the project boundary is the file itself, exactly
# PM-Again's Function/Task/GanttItem convention.

SUITE_TYPES = ("REGRESSION", "UAT", "SMOKE", "INTEGRATION", "OTHER")
REVISION_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED", "ARCHIVED")
REVISION_SOURCE_TYPES = ("MARKDOWN", "XLSX", "CSV", "CLONE", "MANUAL")
MUTATION_LEVELS = ("READ_ONLY", "MUTATING", "MIXED", "UNSPECIFIED")


class TestSuite(ProjectBase):
    __tablename__ = "test_suites"

    id = Column(Integer, primary_key=True, index=True)
    suite_code = Column(String, nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    suite_type = Column(String, default="OTHER")  # REGRESSION|UAT|SMOKE|INTEGRATION|OTHER
    status = Column(String, default="ACTIVE")  # ACTIVE|ARCHIVED
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScriptRevision(ProjectBase):
    """Published revisions are immutable — a correction clones into a new
    DRAFT revision (see routers/revisions.py's clone endpoint); published
    content is never edited in place."""

    __tablename__ = "script_revisions"

    id = Column(Integer, primary_key=True, index=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    revision_label = Column(String, nullable=False)
    revision_number_sort = Column(Integer, nullable=False)
    status = Column(String, default="DRAFT")  # DRAFT|PUBLISHED|SUPERSEDED|ARCHIVED
    change_summary = Column(Text, nullable=True)
    source_type = Column(String, default="MANUAL")  # MARKDOWN|XLSX|CSV|CLONE|MANUAL
    source_filename = Column(String, nullable=True)
    source_sha256 = Column(String, nullable=True)
    imported_at = Column(DateTime, nullable=True)
    imported_by = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String, nullable=True)
    supersedes_revision_id = Column(Integer, ForeignKey("script_revisions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("suite_id", "revision_label", name="uq_revision_suite_label"),)


class TestCase(ProjectBase):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    revision_id = Column(Integer, ForeignKey("script_revisions.id"), nullable=False)
    logical_case_key = Column(String, nullable=True)
    checkpoint_code = Column(String, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    traceability_md = Column(Text, nullable=True)
    fixture_md = Column(Text, nullable=True)
    environment_md = Column(Text, nullable=True)
    setup_md = Column(Text, nullable=True)
    action_md = Column(Text, nullable=False)
    validation_md = Column(Text, nullable=True)
    expected_result_md = Column(Text, nullable=False)
    negative_path = Column(Boolean, default=False)
    mutation_level = Column(String, default="UNSPECIFIED")  # READ_ONLY|MUTATING|MIXED|UNSPECIFIED
    sequence_no = Column(Integer, default=0)
    content_sha256 = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("revision_id", "checkpoint_code", name="uq_case_revision_checkpoint"),)


# ---------- Test cycles and execution (Track A Phase 4) ----------

CYCLE_STATUSES = ("DRAFT", "READY", "IN_PROGRESS", "REVIEW", "COMPLETED", "LOCKED", "CANCELLED")
RESULT_STATUSES = ("NOT_RUN", "PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE")
REVIEW_STATUSES = ("UNREVIEWED", "ACCEPTED", "CHANGES_REQUESTED")
# Hybrid extension points (see docs/hybrid/HYB-0-GAP-ANALYSIS.md) — not
# enabled by this phase, just not designed-away. execution_mode/
# result_source/runner_run_id are real, meaningful columns today (every
# Phase 4 result is MANUAL/HUMAN with no runner_run_id). step_kind/
# checkpoint_status/evidence_source are deliberately NOT added here —
# they only mean something once workflow_steps (HYB-1) exists; adding
# them now would be meaningless nullable columns, not a real hook.
EXECUTION_MODES = ("MANUAL", "AUTOMATED", "HYBRID")
RESULT_SOURCES = ("HUMAN", "RUNNER", "SYSTEM")


class TestCycle(ProjectBase):
    """A cycle snapshots one exact PUBLISHED script revision's case set at
    creation time. Publishing a later revision must never change an
    existing cycle — enforced by simply never re-deriving a cycle's
    result rows from anything but what was created at cycle-creation
    time."""

    __tablename__ = "test_cycles"

    id = Column(Integer, primary_key=True, index=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    script_revision_id = Column(Integer, ForeignKey("script_revisions.id"), nullable=False)
    cycle_code = Column(String, nullable=True)
    name = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    release_version = Column(String, nullable=True)
    target_base_url = Column(String, nullable=True)
    status = Column(String, default="READY")  # see CYCLE_STATUSES
    # PASS-evidence enforcement (rebuild prompt §12) — see routers/
    # cycle_results.py::update_result. Default True: evidence-first is
    # this app's whole premise, so require it unless a project opts out.
    require_evidence_for_pass = Column(Boolean, default=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String, nullable=True)


class CycleTestResult(ProjectBase):
    __tablename__ = "cycle_test_results"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("test_cycles.id"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    assigned_tester_email = Column(String, nullable=True)
    status = Column(String, default="NOT_RUN")  # see RESULT_STATUSES
    actual_result_md = Column(Text, nullable=True)
    blocked_reason = Column(Text, nullable=True)
    na_reason = Column(Text, nullable=True)
    defect_reference = Column(String, nullable=True)  # free text — real `defects` table is a later phase
    started_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    executed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    review_status = Column(String, default="UNREVIEWED")  # see REVIEW_STATUSES
    result_revision_no = Column(Integer, default=0)
    execution_mode = Column(String, default="MANUAL")  # see EXECUTION_MODES — hybrid extension point
    result_source = Column(String, default="HUMAN")  # see RESULT_SOURCES — hybrid extension point
    runner_run_id = Column(Integer, nullable=True)  # reserved: a future hybrid_runs.id, unused until HYB-2
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cycle_id", "test_case_id", name="uq_result_cycle_case"),)


class CycleResultHistory(ProjectBase):
    """Append-only — never edited in place. One row per mutation of a
    CycleTestResult, so a status/actual-result change is never silently
    overwritten (rebuild prompt §12 "Result history")."""

    __tablename__ = "cycle_result_history"

    id = Column(Integer, primary_key=True, index=True)
    cycle_test_result_id = Column(Integer, ForeignKey("cycle_test_results.id"), nullable=False)
    result_revision_no = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    actual_result_md = Column(Text, nullable=True)
    blocked_reason = Column(Text, nullable=True)
    na_reason = Column(Text, nullable=True)
    changed_by = Column(String, nullable=True)
    change_source = Column(String, default="HUMAN")  # see RESULT_SOURCES — hybrid extension point
    changed_at = Column(DateTime, default=datetime.utcnow)


# ---------- Evidence and annotation (Track A Phase 5) ----------

EVIDENCE_TYPES = ("SCREENSHOT", "UPLOADED_IMAGE", "PASTED_IMAGE")
EVIDENCE_STATUSES = ("ACTIVE", "ARCHIVED")


class EvidenceItem(ProjectBase):
    """The original file is immutable once written — never overwritten,
    never re-uploaded in place (rebuild prompt §14 evidence integrity).
    Corrections are new EvidenceRevision rows (annotations), or a brand
    new EvidenceItem; this row's original_* fields never change after
    creation."""

    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("test_cycles.id"), nullable=False)
    cycle_test_result_id = Column(Integer, ForeignKey("cycle_test_results.id"), nullable=False)
    evidence_type = Column(String, nullable=False)  # see EVIDENCE_TYPES
    # A storage-backend-agnostic key (ADR-0002) — a relative filesystem
    # path under FilesystemEvidenceStorage, or an R2 object key under
    # R2EvidenceStorage. Never a filesystem path literal once R2 is in
    # use, hence "object_key" rather than "original_path".
    object_key = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)  # user-supplied, metadata only — never used as the stored key
    original_content_type = Column(String, nullable=False)  # sniffed, not the client's claimed type
    original_size_bytes = Column(Integer, nullable=False)
    original_sha256 = Column(String, nullable=False)
    current_revision_no = Column(Integer, default=0)
    caption = Column(Text, nullable=True)
    target_url = Column(String, nullable=True)
    captured_by = Column(String, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="ACTIVE")  # see EVIDENCE_STATUSES — archive, never delete
    evidence_source = Column(String, default="HUMAN")  # see RESULT_SOURCES — hybrid extension point, unused
    created_at = Column(DateTime, default=datetime.utcnow)


class EvidenceRevision(ProjectBase):
    """Append-only annotation history. Stores design-state JSON (a shapes
    list), not a rendered image per revision — rebuild prompt §14: "do
    not permanently store a full rendered image for every annotation
    revision unless proven necessary." Rendering happens client-side from
    this JSON."""

    __tablename__ = "evidence_revisions"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id"), nullable=False)
    revision_no = Column(Integer, nullable=False)
    annotation_json = Column(Text, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("evidence_id", "revision_no", name="uq_evidence_revision_no"),)


class ActivityLog(ProjectBase):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    field_changed = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_by = Column(String, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)


# ---------- HYB-0 spike: hybrid runner tables ----------
# Deliberately minimal — see docs/hybrid/HYB-0-GAP-ANALYSIS.md section 5
# for why these are spike-scoped, not the full workflow/execution_runs/
# evidence_items model from the hybrid expansion doc's section 8 (that's
# HYB-1+). No cycle_id / cycle_test_result_id / workflow_revision_id yet
# — Track A Phase 4 (test cycles) doesn't exist yet, so those FKs would
# be dishonest placeholders rather than real links.

RUNNER_EVENT_TYPES = (
    "RUN_CLAIMED",
    "STEP_STARTED",
    "STEP_COMPLETED",
    "CHECKPOINT_WAITING",
    "CHECKPOINT_RELEASED",
    "EVIDENCE_UPLOADED",
    "RUN_COMPLETED",
)
ACTOR_TYPES = ("SYSTEM", "RUNNER", "HUMAN")
HYBRID_RUN_STATUSES = (
    "RUNNING",
    "WAITING_FOR_HUMAN",
    "RESUMING",
    "PASSED",
    "FAILED",
    "BLOCKED",
    "NOT_APPLICABLE",
    "CANCELLED",
)
CHECKPOINT_DECISIONS = ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE")


class RunnerToken(MasterBase):
    """A revocable credential a QA Runner process presents on every
    request — deliberately not the full `runners` registration table
    from the hybrid doc's section 8.5 (no heartbeat/capabilities/platform
    yet, that's HYB-2). Stored hashed, same pattern as RefreshToken."""

    __tablename__ = "runner_tokens"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class HybridRun(ProjectBase):
    __tablename__ = "hybrid_runs"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="RUNNING")  # see HYBRID_RUN_STATUSES
    label = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class HybridRunEvent(ProjectBase):
    """Append-only technical event stream — never edited in place. Not a
    substitute for a normalized result table (hybrid doc section 8.9);
    at HYB-0 scale the run's own `status` column is that result."""

    __tablename__ = "hybrid_run_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("hybrid_runs.id"), nullable=False)
    event_type = Column(String, nullable=False)  # see RUNNER_EVENT_TYPES
    actor_type = Column(String, nullable=False)  # SYSTEM | RUNNER | HUMAN
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class HybridCheckpointDecision(ProjectBase):
    """One row per decision, never edited in place — mirrors the
    immutability discipline used everywhere else in this app."""

    __tablename__ = "hybrid_checkpoint_decisions"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("hybrid_runs.id"), nullable=False)
    decision = Column(String, nullable=False)  # see CHECKPOINT_DECISIONS
    reason = Column(Text, nullable=True)
    decided_by = Column(String, nullable=False)
    decided_at = Column(DateTime, default=datetime.utcnow)


class HybridRunEvidence(ProjectBase):
    """Spike-scoped evidence record — see gap analysis section 5 decision
    4 for why this isn't the full evidence_items/evidence_revisions model
    yet. Same core fields so Phase 5 can generalize it later."""

    __tablename__ = "hybrid_run_evidence"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("hybrid_runs.id"), nullable=False)
    original_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    original_content_type = Column(String, nullable=False)
    original_size_bytes = Column(Integer, nullable=False)
    original_sha256 = Column(String, nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow)


# ---------- Defects and sign-offs (Phase 6 prerequisite) ----------
# Both are in the original domain model (rebuild prompt/master spec §10)
# but were never built in an earlier phase — Phase 6's dashboard
# ("open defects by severity") and Excel export (03_NG_Defects,
# 06_Sign_Off sheets) need real data to source, so they're added here
# rather than faked. Deliberately minimal: no defect workflow engine,
# no notification system — just the fields the spec actually lists.

DEFECT_SEVERITIES = ("P0", "P1", "P2", "P3", "UNSPECIFIED")
DEFECT_STATUSES = ("OPEN", "IN_PROGRESS", "FIXED", "RETEST", "CLOSED", "REJECTED")
DEFECT_OPEN_STATUSES = ("OPEN", "IN_PROGRESS", "RETEST")
SIGNOFF_TYPES = ("QA_REVIEW", "BUSINESS_ACCEPTANCE", "GO_LIVE")
SIGNOFF_DECISIONS = ("APPROVED", "REJECTED", "PENDING")


class Defect(ProjectBase):
    __tablename__ = "defects"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("test_cycles.id"), nullable=True)
    cycle_test_result_id = Column(Integer, ForeignKey("cycle_test_results.id"), nullable=True)
    defect_key = Column(String, nullable=False)  # sequential per-project, e.g. DEF-1
    title = Column(String, nullable=False)
    description_md = Column(Text, nullable=True)
    severity = Column(String, default="UNSPECIFIED")  # see DEFECT_SEVERITIES
    status = Column(String, default="OPEN")  # see DEFECT_STATUSES
    external_url = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SignOff(ProjectBase):
    """One row per decision — never edited in place, matching the same
    immutability discipline as HybridCheckpointDecision/CycleResultHistory."""

    __tablename__ = "sign_offs"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("test_cycles.id"), nullable=False)
    signoff_type = Column(String, nullable=False)  # see SIGNOFF_TYPES
    decision = Column(String, nullable=False)  # see SIGNOFF_DECISIONS
    comment_md = Column(Text, nullable=True)
    actor = Column(String, nullable=False)
    acted_at = Column(DateTime, default=datetime.utcnow)


# ---------- HYB-1: workflow model and editor ----------
# See docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md for the design decisions
# this implements. Mirrors TestSuite/ScriptRevision/TestCase's
# immutable-revision + clone-for-correction pattern exactly (same
# DRAFT|PUBLISHED|SUPERSEDED lifecycle) so the discipline that already
# protects test scripts protects automated workflows too.

WORKFLOW_REVISION_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
WORKFLOW_STEP_TYPES = (
    "NAVIGATE", "CLICK", "FILL", "SELECT", "CHECK", "UNCHECK", "PRESS_KEY",
    "WAIT_FOR_ELEMENT", "ASSERT_VISIBLE", "ASSERT_TEXT", "ASSERT_URL",
    "SCREENSHOT", "MANUAL_CHECKPOINT",
)
LOCATOR_STRATEGIES = ("TEST_ID", "ROLE", "LABEL", "PLACEHOLDER", "TEXT", "CSS", "XPATH")
LOCATOR_SOURCES = ("MANUAL", "RECORDER", "IMPORTED")  # HYB-3 sets RECORDER
EVIDENCE_POLICIES = ("NONE", "OPTIONAL", "REQUIRED")


class WorkflowDefinition(ProjectBase):
    """Stable identity across revisions — mirrors TestSuite's role for
    ScriptRevision."""

    __tablename__ = "workflow_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="ACTIVE")  # ACTIVE|ARCHIVED
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowRevision(ProjectBase):
    """Immutable once PUBLISHED — a correction clones into a new DRAFT,
    exactly like ScriptRevision. This is the entity a WorkflowRun (HYB-2)
    will point to; a run must never silently follow a newer revision."""

    __tablename__ = "workflow_revisions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflow_definitions.id"), nullable=False)
    revision_label = Column(String, nullable=False)
    revision_number_sort = Column(Integer, nullable=False)
    status = Column(String, default="DRAFT")  # see WORKFLOW_REVISION_STATUSES
    change_summary = Column(Text, nullable=True)
    supersedes_revision_id = Column(Integer, ForeignKey("workflow_revisions.id"), nullable=True)
    created_by = Column(String, nullable=True)
    published_by = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("workflow_id", "revision_label", name="uq_workflow_revision_label"),)


class WorkflowStep(ProjectBase):
    """Ordered step within a DRAFT revision — mutable only while the
    parent revision is DRAFT (enforced in the router, not the model,
    matching TestCase's own pattern)."""

    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("workflow_revisions.id"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    step_type = Column(String, nullable=False)  # see WORKFLOW_STEP_TYPES
    description = Column(String, nullable=True)
    # Structured locator (rebuild-hybrid-doc-required — never raw source
    # code, never raw x/y). `locator_fallbacks_json` is a JSON list of
    # {strategy, value} candidates in priority order.
    locator_strategy = Column(String, nullable=True)  # see LOCATOR_STRATEGIES
    locator_value = Column(String, nullable=True)
    locator_fallbacks_json = Column(Text, nullable=True)
    locator_source = Column(String, default="MANUAL")  # see LOCATOR_SOURCES
    # Literal value, or a "${VAR_NAME}" reference — never a real secret
    # value when is_sensitive is true (enforced at the router, not just
    # documented: see workflows.py's _validate_step).
    input_value = Column(Text, nullable=True)
    is_sensitive = Column(Boolean, default=False)
    timeout_ms = Column(Integer, nullable=True)
    expected_value = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    checkpoint_instructions = Column(Text, nullable=True)  # MANUAL_CHECKPOINT only
    evidence_policy = Column(String, default="NONE")  # see EVIDENCE_POLICIES
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowTestCaseLink(ProjectBase):
    """Links a workflow revision to a Track A test case.

    Deliberately carries BOTH:
      - `test_case_id`: the exact TestCase row used by this workflow
        revision. TestCase rows are already immutable once their parent
        ScriptRevision publishes (Phase 3 invariant) — pointing at this
        id IS the exact immutable snapshot; it is never repointed after
        creation, so a historical workflow run can never silently follow
        a newer test-case revision.
      - `logical_case_key`: copied from TestCase.logical_case_key (or
        checkpoint_code if that's unset) at link time — the stable
        identity used for "what's the current case for this logical
        checkpoint" navigation/relationship queries, independent of
        which exact revision this link snapshotted.
    See docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md section 2, decision 1.
    """

    __tablename__ = "workflow_test_case_links"

    id = Column(Integer, primary_key=True, index=True)
    workflow_revision_id = Column(Integer, ForeignKey("workflow_revisions.id"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    logical_case_key = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("workflow_revision_id", "test_case_id", name="uq_workflow_revision_case"),
    )
