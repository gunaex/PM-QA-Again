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


class ProjectMembership(MasterBase):
    """ADR-0003: layers per-project access on top of the still-global role
    from ADR-0001 -- a TESTER/VIEWER can only reach a project they have a
    row for here; ADMIN bypasses this table entirely (see
    require_project_access in auth.py). Plain FK columns, no relationship()
    -- matches every other model in this file (manual .query().filter()
    joins throughout, never ORM relationships)."""

    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
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
    # Quick Manual Test entry flow: the one shared "Quick Tests" suite a
    # project auto-creates on first use is flagged so the formal Suite
    # list hides it by default (toggle to show) -- it is still a fully
    # real TestSuite row, fully auditable/exportable, never a parallel
    # ad-hoc model.
    is_system_generated = Column(Boolean, default=False)


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
    # Quick Manual Test entry flow -- denormalized copy of the owning
    # suite's own is_system_generated flag at creation time (a rerun
    # inherits its source cycle's own value, so a rerun of a formal
    # cycle stays visible and a rerun of a quick test stays hidden).
    # Avoids a join on the hot cycle-list query.
    is_system_generated = Column(Boolean, default=False)


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
    # HYB-2/HYB-1-gap-analysis decision 2: hybrid evidence reuses this
    # table rather than a parallel subsystem. Both nullable — every
    # Track A row leaves them null; a runner-captured screenshot sets
    # workflow_run_id (+ workflow_step_run_id when tied to one specific
    # step) and evidence_source=RUNNER. checkpoint_decision_id is
    # deliberately NOT added yet — it would be meaningless until HYB-4's
    # checkpoint-decision model exists to reference.
    workflow_run_id = Column(Integer, nullable=True)
    workflow_step_run_id = Column(Integer, nullable=True)
    # HYB-5: server-side timing of this upload's own read+sniff+hash+store
    # work (not client network transfer time — the server never sees the
    # client's own upload-start moment). Null for every pre-HYB-5 row and
    # for Track A's own tester-driven upload endpoint (evidence.py), which
    # does not measure this.
    upload_duration_ms = Column(Integer, nullable=True)
    # HYB-4: set (server-side, never client-supplied) when a reviewer
    # attaches this evidence to a specific checkpoint decision at
    # decision-submission time -- the column the HYB-1 gap-analysis
    # deferred specifically to this phase. Nullable/additive; every prior
    # row (Track A, HYB-2 runner screenshots) leaves it null.
    checkpoint_decision_id = Column(Integer, ForeignKey("workflow_checkpoint_decisions.id"), nullable=True)


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
    request. HYB-0 shipped this as a bare credential; HYB-2 extends it
    with the registration/heartbeat fields the hybrid doc's section 8.5
    asks for (name/version/platform/capabilities/last heartbeat) rather
    than introducing a second `runners` table — one runner process still
    equals one token in this MVP, so splitting identity from credential
    would be a distinction without a use yet. Stored hashed, same
    pattern as RefreshToken."""

    __tablename__ = "runner_tokens"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # HYB-2 registration/heartbeat fields — all nullable: a token minted
    # before HYB-2 (or never yet used by a real runner process) simply
    # has none of this filled in until the runner's first real call.
    runner_name = Column(String, nullable=True)
    runner_version = Column(String, nullable=True)
    os_metadata = Column(String, nullable=True)
    browser_version = Column(String, nullable=True)
    capabilities_json = Column(Text, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)


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
    # HYB-4: optional links so a defect raised from a checkpoint review
    # carries its full provenance (run/step/decision), reusing this same
    # table rather than a parallel hybrid defect model. All nullable —
    # every pre-HYB-4 defect leaves them null.
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=True)
    workflow_step_run_id = Column(Integer, ForeignKey("workflow_step_runs.id"), nullable=True)
    checkpoint_decision_id = Column(Integer, ForeignKey("workflow_checkpoint_decisions.id"), nullable=True)


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
    "WAIT_FOR_ELEMENT", "WAIT", "ASSERT_VISIBLE", "ASSERT_TEXT", "ASSERT_URL",
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
    # When set (>1), the runner re-executes this single step in place
    # this many times before advancing -- the "click this 5 times"
    # macro case. Null/1 means run once, same as before this column
    # existed. See runner/src/execution/executor.ts.
    repeat_count = Column(Integer, nullable=True)
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


# ---------- HYB-2: runner registration and execution ----------
# See docs/hybrid/SESSION_HANDOFF.md and docs/Autonomous hybird prompt.md's
# HYB-2 section. A WorkflowRun always targets a PUBLISHED WorkflowRevision
# (enforced in the router, not the model) -- never a DRAFT, so a run's
# steps can never change out from under it mid-execution.

WORKFLOW_RUN_STATUSES = (
    "WAITING_FOR_TARGET", "READY", "QUEUED", "CLAIMED", "STARTING", "RUNNING", "PAUSED", "WAITING_FOR_HUMAN",
    "RESUMING", "PASSED", "FAILED", "BLOCKED", "NOT_APPLICABLE", "CANCELLED",
    "RUNNER_LOST", "SYSTEM_ERROR",
)
# Terminal: no further mutation, no further lease. WAITING_FOR_HUMAN and
# RESUMING are deliberately NOT terminal -- HYB-4's decision/resume
# protocol moves a run through them -- but ARE now lease-tracked (see
# WORKFLOW_RUN_PAUSED_LEASE_STATUSES below): a runner that stops
# heartbeating while paused must still be detected as lost, just on a
# longer timeout than the active-execution lease.
WORKFLOW_RUN_TERMINAL_STATUSES = (
    "PASSED", "FAILED", "BLOCKED", "NOT_APPLICABLE", "CANCELLED", "RUNNER_LOST", "SYSTEM_ERROR",
)
WORKFLOW_RUN_LEASED_STATUSES = ("CLAIMED", "STARTING", "RUNNING")
# HYB-4: the runner keeps heartbeating and its lease alive while paused at
# a checkpoint and while resuming, just under a much longer timeout (a
# human deciding takes arbitrarily long; a 60s active-execution lease
# would false-positive RUNNER_LOST on every real checkpoint).
WORKFLOW_RUN_PAUSED_LEASE_STATUSES = ("WAITING_FOR_HUMAN", "RESUMING")
PAUSED_LEASE_DURATION_SECONDS = 300

STEP_RUN_STATUSES = ("PENDING", "RUNNING", "PASSED", "FAILED", "SKIPPED")
FAILURE_CATEGORIES = (
    "LOCATOR_NOT_FOUND", "LOCATOR_AMBIGUOUS", "TIMEOUT", "NAVIGATION_ERROR",
    "ASSERTION_FAILED", "INPUT_ERROR", "BROWSER_CRASH", "RUNNER_DISCONNECTED",
    "CANCELLED", "SYSTEM_ERROR",
)
RUNNER_EXEC_EVENT_TYPES = (
    "RUN_QUEUED", "RUN_CLAIMED", "STEP_STARTED", "STEP_COMPLETED", "STEP_FAILED",
    "CHECKPOINT_WAITING", "HEARTBEAT", "RUN_CANCELLED", "RUN_COMPLETED", "RUNNER_LOST",
    # HYB-4
    "CHECKPOINT_DECIDED", "RUN_RESUMED", "TARGET_ATTACHED", "EVIDENCE_UPLOADED",
)

LEASE_DURATION_SECONDS = 60

# ---------- HYB-4: manual checkpoint decisions ----------
# One row per decision, append-only -- never edited, never overwritten.
# Decision-conflict protection is NOT a column on this table: it's the
# atomic run.status compare-and-swap in routers/workflow_runs.py's
# submit_checkpoint_decision (the run must be WAITING_FOR_HUMAN, and the
# same transaction that inserts this row also flips run.status away from
# WAITING_FOR_HUMAN) -- exactly the "first commit wins" pattern already
# used for the evidence-upload quota race (see evidence.py). A second
# racing decision simply finds run.status no longer WAITING_FOR_HUMAN and
# is rejected with 409, never silently overwriting the first row.
CHECKPOINT_DECISION_STATUSES = CHECKPOINT_DECISIONS  # PASS|FAIL|BLOCKED|NOT_APPLICABLE -- same vocabulary as the HYB-0 spike


class WorkflowCheckpointDecision(ProjectBase):
    __tablename__ = "workflow_checkpoint_decisions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    workflow_step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    workflow_step_run_id = Column(Integer, ForeignKey("workflow_step_runs.id"), nullable=True)
    # Monotonically increasing per (workflow_run_id, workflow_step_id) --
    # always 1 in the common case (a checkpoint occurrence is decided
    # exactly once thanks to the CAS above), but the column exists so a
    # deliberate rerun/re-checkpoint scenario has an honest place to
    # record "this is the Nth decision for this exact checkpoint
    # occurrence" without ever reusing or editing row 1.
    decision_revision_no = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False)  # see CHECKPOINT_DECISION_STATUSES
    actual_result_md = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    # Server-derived, never trusted from the frontend -- set from the
    # authenticated user session in the router, exactly like every other
    # *_by/*_at column in this app.
    decided_by_user_id = Column(Integer, nullable=False)  # master DB users.id -- cross-DB, not a real FK
    decided_by_email = Column(String, nullable=False)
    decided_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String, default="HUMAN")  # always HUMAN -- see RESULT_SOURCES; this table has no RUNNER/SYSTEM path
    resume_authorized = Column(Boolean, nullable=False)  # True only for PASS
    # NOT_APPLICABLE mirrors CycleTestResult's own admin-review policy
    # (routers/cycle_results.py::review_result) rather than inventing a
    # second one.
    review_status = Column(String, nullable=True)  # UNREVIEWED|ACCEPTED|CHANGES_REQUESTED -- NOT_APPLICABLE only
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("workflow_run_id", "workflow_step_id", "decision_revision_no", name="uq_checkpoint_decision_revision"),
        UniqueConstraint("workflow_run_id", "workflow_step_id", "idempotency_key", name="uq_checkpoint_decision_idempotency"),
    )


class WorkflowRun(ProjectBase):
    """One execution of a published workflow revision. Lease fields
    (`lease_token`/`lease_expires_at`) implement HYB-2's "time-limited
    lease + renewal" requirement directly on the run rather than via a
    separate lease table -- a run has at most one active claim at a
    time in this MVP (no multi-runner fan-out), so a dedicated table
    would track a 1:1 relationship a column pair already expresses."""

    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_revision_id = Column(Integer, ForeignKey("workflow_revisions.id"), nullable=False)
    # Optional: ties a hybrid run to a specific Track A cycle result, the
    # real-world case evidence/results should flow into. A run with no
    # cycle_test_result_id is a standalone workflow execution (e.g.
    # testing the workflow itself) -- evidence upload requires this to
    # be set (enforced in the router), preserving EvidenceItem's existing
    # NOT NULL cycle_id/cycle_test_result_id invariant unchanged.
    cycle_test_result_id = Column(Integer, ForeignKey("cycle_test_results.id"), nullable=True)
    status = Column(String, default="QUEUED")  # see WORKFLOW_RUN_STATUSES
    runner_id = Column(Integer, nullable=True)  # RunnerToken.id (master DB) -- cross-DB, not a real FK
    lease_token = Column(String, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    cancel_requested = Column(Boolean, default=False)
    queued_by = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    result_summary = Column(Text, nullable=True)
    # HYB-4: set when the run enters WAITING_FOR_HUMAN, cleared on resume
    # or terminal decision -- powers the checkpoint UI's elapsed-waiting-
    # time display without recomputing it from the event log every poll.
    checkpoint_waiting_since = Column(DateTime, nullable=True)
    # Phase E: a tester's own "Test It Now" sanity check against a DRAFT
    # revision -- runs through the exact same claim/execute/report path
    # as a real run, but is never counted in Track A/B reporting/export
    # and can never carry a cycle_test_result_id (enforced in the
    # preview-run router, not just this default). Keeps the ADMIN-only
    # publish gate meaningful: a preview never becomes part of the
    # audited record no matter how many times it's re-run.
    is_preview = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowRunBrowserAuthorization(ProjectBase):
    """Short-lived credential that lets the Chrome extension execute one
    exact WorkflowRun in one tester-selected tab. The raw token is returned
    once in the pairing code and only its hash is persisted."""

    __tablename__ = "workflow_run_browser_authorizations"

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False, unique=True, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    connected_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowStepRun(ProjectBase):
    """One row per (attempted) step execution -- structured, queryable
    history, distinct from the raw RunnerExecutionEvent log."""

    __tablename__ = "workflow_step_runs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    workflow_step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    attempt_number = Column(Integer, default=1)
    status = Column(String, default="PENDING")  # see STEP_RUN_STATUSES
    outcome = Column(Text, nullable=True)
    failure_category = Column(String, nullable=True)  # see FAILURE_CATEGORIES
    machine_message = Column(Text, nullable=True)
    locator_used_json = Column(Text, nullable=True)
    # Browser-observed action duration. Kept separately from timestamps
    # so sub-second measurements are not lost and reports stay simple.
    duration_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowRunScreenshot(ProjectBase):
    """Immutable screenshot captured from the tester-selected tab."""

    __tablename__ = "workflow_run_screenshots"

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    workflow_step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    object_key = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    captured_by = Column(String, default="BROWSER_EXTENSION")
    upload_duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RunnerExecutionEvent(ProjectBase):
    """Append-only raw event stream for a WorkflowRun. Idempotent
    delivery: (workflow_run_id, idempotency_key) is unique whenever the
    runner supplies a key, so a retried POST (e.g. after a network blip)
    returns the original row instead of creating a duplicate. Events
    without a key (e.g. HEARTBEAT) aren't dedup-sensitive and skip this."""

    __tablename__ = "runner_execution_events"

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    event_type = Column(String, nullable=False)  # see RUNNER_EXEC_EVENT_TYPES
    actor_type = Column(String, default="RUNNER")  # see RESULT_SOURCES (HUMAN|RUNNER|SYSTEM)
    idempotency_key = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("workflow_run_id", "idempotency_key", name="uq_run_event_idempotency"),
    )


# ---------- HYB-3: browser workflow recorder ----------
# Recording happens only inside a Playwright browser the QA Runner
# itself launches (never the tester's own everyday browser, never a
# global OS hook) -- see runner/src/recorder/. A RecordingSession is a
# claim/lease job exactly like WorkflowRun (same outbound-only /claim
# protocol, same lease fields), except its payload is a buffer of
# candidate RecordedStep rows for a human to review, not an execution.
# Stopping recording never publishes anything -- "save as draft" is a
# separate, explicit action that reuses HYB-1's own revision/step
# creation code, so a recorded draft is indistinguishable from a
# hand-built one once saved.

RECORDING_SESSION_STATUSES = ("REQUESTED", "CLAIMED", "RECORDING", "PAUSED", "STOPPED", "DISCARDED", "SAVED", "RUNNER_LOST")
RECORDING_SESSION_LEASED_STATUSES = ("CLAIMED", "RECORDING", "PAUSED")


class RecordingSession(ProjectBase):
    __tablename__ = "recording_sessions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflow_definitions.id"), nullable=False)
    status = Column(String, default="REQUESTED")  # see RECORDING_SESSION_STATUSES
    target_url = Column(String, nullable=False)
    requested_by = Column(String, nullable=True)
    runner_id = Column(Integer, nullable=True)  # RunnerToken.id (master DB) -- cross-DB, not a real FK
    lease_token = Column(String, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ADR-HYB-002: set when this session is populated via the Chrome
    # extension mode instead of the Playwright-controlled runner mode --
    # mutually exclusive with runner_id in practice (a session is
    # recorded by one or the other), both nullable so neither mode
    # requires the other's column.
    extension_authorization_id = Column(Integer, ForeignKey("recording_session_authorizations.id"), nullable=True)


class RecordedStep(ProjectBase):
    """One candidate step captured during a RecordingSession. Distinct
    from WorkflowStep on purpose -- this is an editable, discardable
    draft buffer; it only becomes a real WorkflowStep when the tester
    explicitly saves the session (see recording_sessions.py::
    save_as_draft)."""

    __tablename__ = "recorded_steps"

    id = Column(Integer, primary_key=True, index=True)
    recording_session_id = Column(Integer, ForeignKey("recording_sessions.id"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    step_type = Column(String, nullable=False)  # see WORKFLOW_STEP_TYPES (HYB-1) -- same enum, no new types added
    description = Column(String, nullable=True)
    locator_strategy = Column(String, nullable=True)  # see LOCATOR_STRATEGIES (HYB-1)
    locator_value = Column(String, nullable=True)
    locator_fallbacks_json = Column(Text, nullable=True)
    locator_warnings_json = Column(Text, nullable=True)  # e.g. ["no data-testid; matched by visible text"]
    target_summary = Column(String, nullable=True)  # short, truncated element description -- never a full DOM dump
    page_context = Column(String, nullable=True)  # URL path at capture time
    # Coordinates are optional DIAGNOSTIC metadata only -- never used as
    # a locator strategy value, never resolved against during replay.
    diagnostic_x = Column(Integer, nullable=True)
    diagnostic_y = Column(Integer, nullable=True)
    input_value = Column(Text, nullable=True)  # never set (stays null) for is_sensitive rows
    is_sensitive = Column(Boolean, default=False)
    expected_value = Column(Text, nullable=True)
    checkpoint_instructions = Column(Text, nullable=True)
    needs_review = Column(Boolean, default=False)  # an uncertain noise-reduction simplification -- flagged, not silently applied
    review_note = Column(String, nullable=True)
    # "Test this locator" -- a tester requests it (while the recording
    # browser is still alive), the runner picks it up on its next poll,
    # evaluates it with the *same* resolveLocator() replay will use, and
    # posts the result back. Simple request/result pair on the row
    # itself rather than a separate table -- one outstanding test at a
    # time per step is all the MVP needs.
    locator_test_requested = Column(Boolean, default=False)
    locator_test_result_json = Column(Text, nullable=True)
    # ADR-HYB-002 fix: idempotent replay was previously (incorrectly)
    # checked against `review_note` with a key that was never actually
    # written there -- a real pre-existing bug (idempotency silently
    # never worked for either recording mode). A dedicated column, set
    # whenever the caller supplies one, fixes this for both modes.
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # No DB-level uniqueness on (recording_session_id, sequence_no) --
    # matches WorkflowStep's own reorder endpoint (HYB-1), which relies
    # on application-level ordering rather than a constraint, precisely
    # to avoid an intermediate collision while a batch of UPDATEs is
    # mid-flight during a reorder.


# ---------- Chrome extension recorder (ADR-HYB-002) ----------
# A deliberately narrower credential than either the tester's own JWT
# (long-lived, every project) or the global RunnerToken (long-lived,
# every project): scoped to exactly one recording_session_id, short-
# lived, revoked on stop/expiry. See
# docs/hybrid/CHROME_EXTENSION_RECORDER.md for the full design. This is
# the ONLY new table this feature adds -- RecordingSession/RecordedStep
# and every review/save-as-draft/publish code path are fully reused,
# unchanged.

RECORDING_SESSION_AUTH_DURATION_SECONDS = 30 * 60  # 30 min per renewal
RECORDING_SESSION_AUTH_HARD_CAP_SECONDS = 4 * 60 * 60  # 4 hours total, never renewed past this


class RecordingSessionAuthorization(ProjectBase):
    __tablename__ = "recording_session_authorizations"

    id = Column(Integer, primary_key=True, index=True)
    recording_session_id = Column(Integer, ForeignKey("recording_sessions.id"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    issued_by = Column(String, nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    # Hard cap on total lifetime regardless of renewal -- see
    # RECORDING_SESSION_AUTH_HARD_CAP_SECONDS. A heartbeat past this
    # point is rejected even though expires_at hasn't been reached yet.
    hard_cap_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
