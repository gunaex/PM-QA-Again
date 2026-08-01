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
    # HYB-2/HYB-1-gap-analysis decision 2: hybrid evidence reuses this
    # table rather than a parallel subsystem. Both nullable — every
    # Track A row leaves them null; a runner-captured screenshot sets
    # workflow_run_id (+ workflow_step_run_id when tied to one specific
    # step) and evidence_source=RUNNER. checkpoint_decision_id is
    # deliberately NOT added yet — it would be meaningless until HYB-4's
    # checkpoint-decision model exists to reference.
    workflow_run_id = Column(Integer, nullable=True)
    workflow_step_run_id = Column(Integer, nullable=True)


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


# ---------- HYB-2: runner registration and execution ----------
# See docs/hybrid/SESSION_HANDOFF.md and docs/Autonomous hybird prompt.md's
# HYB-2 section. A WorkflowRun always targets a PUBLISHED WorkflowRevision
# (enforced in the router, not the model) -- never a DRAFT, so a run's
# steps can never change out from under it mid-execution.

WORKFLOW_RUN_STATUSES = (
    "QUEUED", "CLAIMED", "STARTING", "RUNNING", "PAUSED", "WAITING_FOR_HUMAN",
    "RESUMING", "PASSED", "FAILED", "BLOCKED", "CANCELLED", "RUNNER_LOST", "SYSTEM_ERROR",
)
# Terminal: no further mutation, no further lease. WAITING_FOR_HUMAN is
# deliberately NOT terminal (HYB-4 resumes it) and deliberately NOT
# lease-tracked (a human deciding takes arbitrarily long; only the
# runner's own active-execution window is lease-bound).
WORKFLOW_RUN_TERMINAL_STATUSES = ("PASSED", "FAILED", "BLOCKED", "CANCELLED", "RUNNER_LOST", "SYSTEM_ERROR")
WORKFLOW_RUN_LEASED_STATUSES = ("CLAIMED", "STARTING", "RUNNING")

STEP_RUN_STATUSES = ("PENDING", "RUNNING", "PASSED", "FAILED", "SKIPPED")
FAILURE_CATEGORIES = (
    "LOCATOR_NOT_FOUND", "LOCATOR_AMBIGUOUS", "TIMEOUT", "NAVIGATION_ERROR",
    "ASSERTION_FAILED", "INPUT_ERROR", "BROWSER_CRASH", "RUNNER_DISCONNECTED",
    "CANCELLED", "SYSTEM_ERROR",
)
RUNNER_EXEC_EVENT_TYPES = (
    "RUN_QUEUED", "RUN_CLAIMED", "STEP_STARTED", "STEP_COMPLETED", "STEP_FAILED",
    "CHECKPOINT_WAITING", "HEARTBEAT", "RUN_CANCELLED", "RUN_COMPLETED", "RUNNER_LOST",
)

LEASE_DURATION_SECONDS = 60


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
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
