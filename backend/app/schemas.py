from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    must_change_password: bool

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    name: str
    external_project_url: Optional[str] = None


class ProjectArchiveRequest(BaseModel):
    archived: bool
    password: str


class ProjectDeleteRequest(BaseModel):
    password: str


class ProjectOut(BaseModel):
    id: int
    name: str
    slug: str
    external_project_url: Optional[str] = None
    archived: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Test suites ----------


class TestSuiteCreate(BaseModel):
    name: str
    suite_code: Optional[str] = None
    description: Optional[str] = None
    suite_type: str = "OTHER"


class TestSuiteUpdate(BaseModel):
    name: Optional[str] = None
    suite_code: Optional[str] = None
    description: Optional[str] = None
    suite_type: Optional[str] = None
    status: Optional[str] = None


class TestSuiteOut(BaseModel):
    id: int
    suite_code: Optional[str] = None
    name: str
    description: Optional[str] = None
    suite_type: str
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Script revisions ----------


class RevisionCreate(BaseModel):
    revision_label: str
    change_summary: Optional[str] = None


class RevisionPublishRequest(BaseModel):
    published_by: Optional[str] = None


class RevisionCloneRequest(BaseModel):
    revision_label: str
    change_summary: Optional[str] = None
    created_by: Optional[str] = None


class RevisionOut(BaseModel):
    id: int
    suite_id: int
    revision_label: str
    revision_number_sort: int
    status: str
    change_summary: Optional[str] = None
    source_type: str
    source_filename: Optional[str] = None
    source_sha256: Optional[str] = None
    imported_at: Optional[datetime] = None
    imported_by: Optional[str] = None
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None
    supersedes_revision_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Test cases ----------


class TestCaseCreate(BaseModel):
    checkpoint_code: str
    title: str
    logical_case_key: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    traceability_md: Optional[str] = None
    fixture_md: Optional[str] = None
    environment_md: Optional[str] = None
    setup_md: Optional[str] = None
    action_md: str
    validation_md: Optional[str] = None
    expected_result_md: str
    negative_path: bool = False
    mutation_level: str = "UNSPECIFIED"
    sequence_no: int = 0


class TestCaseUpdate(BaseModel):
    checkpoint_code: Optional[str] = None
    title: Optional[str] = None
    logical_case_key: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    traceability_md: Optional[str] = None
    fixture_md: Optional[str] = None
    environment_md: Optional[str] = None
    setup_md: Optional[str] = None
    action_md: Optional[str] = None
    validation_md: Optional[str] = None
    expected_result_md: Optional[str] = None
    negative_path: Optional[bool] = None
    mutation_level: Optional[str] = None
    sequence_no: Optional[int] = None


class TestCaseOut(BaseModel):
    id: int
    suite_id: int
    revision_id: int
    logical_case_key: Optional[str] = None
    checkpoint_code: str
    title: str
    category: Optional[str] = None
    priority: Optional[str] = None
    traceability_md: Optional[str] = None
    fixture_md: Optional[str] = None
    environment_md: Optional[str] = None
    setup_md: Optional[str] = None
    action_md: str
    validation_md: Optional[str] = None
    expected_result_md: str
    negative_path: bool
    mutation_level: str
    sequence_no: int
    content_sha256: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- HYB-0 spike ----------


class RunnerTokenCreate(BaseModel):
    label: str


class RunnerTokenOut(BaseModel):
    id: int
    label: str
    token: str  # raw token — returned once, at creation, never again


class HybridRunCreate(BaseModel):
    label: Optional[str] = None


class HybridRunOut(BaseModel):
    id: int
    status: str
    label: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HybridRunEventCreate(BaseModel):
    event_type: str
    actor_type: str
    payload_json: Optional[str] = None


class HybridRunEventOut(BaseModel):
    id: int
    run_id: int
    event_type: str
    actor_type: str
    payload_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HybridRunDetailOut(HybridRunOut):
    events: list[HybridRunEventOut] = []
    latest_decision: Optional["HybridCheckpointDecisionOut"] = None


class HybridCheckpointDecisionCreate(BaseModel):
    decision: str
    reason: Optional[str] = None


class HybridCheckpointDecisionOut(BaseModel):
    id: int
    run_id: int
    decision: str
    reason: Optional[str] = None
    decided_by: str
    decided_at: datetime

    class Config:
        from_attributes = True


class HybridRunEvidenceOut(BaseModel):
    id: int
    run_id: int
    original_filename: str
    original_content_type: str
    original_size_bytes: int
    original_sha256: str
    captured_at: datetime

    class Config:
        from_attributes = True


HybridRunDetailOut.model_rebuild()


# ---------- Test cycles and execution (Phase 4) ----------


class TestCycleCreate(BaseModel):
    suite_id: int
    script_revision_id: int
    name: str
    environment: str
    cycle_code: Optional[str] = None
    release_version: Optional[str] = None
    target_base_url: Optional[str] = None
    require_evidence_for_pass: bool = True


class TestCycleUpdate(BaseModel):
    name: Optional[str] = None
    environment: Optional[str] = None
    cycle_code: Optional[str] = None
    release_version: Optional[str] = None
    target_base_url: Optional[str] = None
    status: Optional[str] = None  # any status except LOCKED — use /lock and /reopen for that
    require_evidence_for_pass: Optional[bool] = None


class CycleReopenRequest(BaseModel):
    reason: str


class ResultCounts(BaseModel):
    NOT_RUN: int = 0
    PASS: int = 0
    FAIL: int = 0
    BLOCKED: int = 0
    NOT_APPLICABLE: int = 0


class TestCycleOut(BaseModel):
    id: int
    suite_id: int
    script_revision_id: int
    cycle_code: Optional[str] = None
    name: str
    environment: str
    release_version: Optional[str] = None
    target_base_url: Optional[str] = None
    status: str
    require_evidence_for_pass: bool
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    result_counts: Optional[ResultCounts] = None

    class Config:
        from_attributes = True


class CycleTestResultUpdate(BaseModel):
    status: str
    actual_result_md: Optional[str] = None
    blocked_reason: Optional[str] = None
    na_reason: Optional[str] = None
    defect_reference: Optional[str] = None
    assigned_tester_email: Optional[str] = None


class CycleTestResultListOut(BaseModel):
    """Lightweight shape for the results *list* endpoint — everything the
    Cycle Execution sidebar needs to render, deliberately excluding the
    four case markdown fields (action/expected/setup/validation), which
    can be large and are only needed once a specific case is opened. See
    docs/PERFORMANCE_FAST_PASS.md — the full list used to embed those
    fields on every one of up to hundreds of rows, making initial cycle
    load payload-bound rather than query-bound."""

    id: int
    cycle_id: int
    test_case_id: int
    assigned_tester_email: Optional[str] = None
    status: str
    actual_result_md: Optional[str] = None
    blocked_reason: Optional[str] = None
    na_reason: Optional[str] = None
    defect_reference: Optional[str] = None
    started_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    executed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    review_status: str
    result_revision_no: int
    execution_mode: str
    result_source: str
    runner_run_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Flattened from the linked TestCase so the execution screen doesn't
    # need a second round trip per row.
    checkpoint_code: Optional[str] = None
    case_title: Optional[str] = None
    case_priority: Optional[str] = None

    class Config:
        from_attributes = True


class CycleTestResultOut(CycleTestResultListOut):
    """Full shape — adds the case markdown fields. Used by the single-
    result detail/update/review endpoints, fetched only for the result
    currently open in the execution screen."""

    case_action_md: Optional[str] = None
    case_expected_result_md: Optional[str] = None
    case_setup_md: Optional[str] = None
    case_validation_md: Optional[str] = None


class CycleResultReviewRequest(BaseModel):
    review_status: str  # ACCEPTED | CHANGES_REQUESTED
    comment: Optional[str] = None


class CycleResultHistoryOut(BaseModel):
    id: int
    cycle_test_result_id: int
    result_revision_no: int
    status: str
    actual_result_md: Optional[str] = None
    blocked_reason: Optional[str] = None
    na_reason: Optional[str] = None
    changed_by: Optional[str] = None
    change_source: str
    changed_at: datetime

    class Config:
        from_attributes = True


# ---------- Evidence and annotation (Phase 5) ----------


class EvidenceItemOut(BaseModel):
    id: int
    cycle_id: int
    cycle_test_result_id: int
    evidence_type: str
    original_filename: str
    original_content_type: str
    original_size_bytes: int
    original_sha256: str
    current_revision_no: int
    caption: Optional[str] = None
    target_url: Optional[str] = None
    captured_by: Optional[str] = None
    captured_at: datetime
    status: str
    evidence_source: str
    created_at: datetime

    class Config:
        from_attributes = True


class EvidenceCaptionUpdate(BaseModel):
    caption: Optional[str] = None
    target_url: Optional[str] = None


class AnnotationRevisionCreate(BaseModel):
    annotation_json: str
    change_summary: Optional[str] = None


class AnnotationRevisionOut(BaseModel):
    id: int
    evidence_id: int
    revision_no: int
    annotation_json: str
    change_summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StorageQuotaOut(BaseModel):
    used_bytes: int
    quota_bytes: int
    percent_used: float
    threshold_level: int
    thresholds: list[int]
    over_quota: bool


class StorageQuotaUpdate(BaseModel):
    storage_quota_bytes: Optional[int] = None
    storage_warning_thresholds: Optional[list[int]] = None


# ---------- Defects and sign-offs (Phase 6) ----------


class DefectCreate(BaseModel):
    title: str
    cycle_id: Optional[int] = None
    cycle_test_result_id: Optional[int] = None
    description_md: Optional[str] = None
    severity: str = "UNSPECIFIED"
    external_url: Optional[str] = None


class DefectUpdate(BaseModel):
    title: Optional[str] = None
    description_md: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    external_url: Optional[str] = None


class DefectOut(BaseModel):
    id: int
    cycle_id: Optional[int] = None
    cycle_test_result_id: Optional[int] = None
    defect_key: str
    title: str
    description_md: Optional[str] = None
    severity: str
    status: str
    external_url: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SignOffCreate(BaseModel):
    cycle_id: int
    signoff_type: str
    decision: str
    comment_md: Optional[str] = None


class SignOffOut(BaseModel):
    id: int
    cycle_id: int
    signoff_type: str
    decision: str
    comment_md: Optional[str] = None
    actor: str
    acted_at: datetime

    class Config:
        from_attributes = True


# ---------- HYB-1: workflow model and editor ----------


class WorkflowDefinitionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class WorkflowDefinitionOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Convenience for the list screen — avoids a second round trip per row.
    published_revision_id: Optional[int] = None
    published_revision_label: Optional[str] = None

    class Config:
        from_attributes = True


class WorkflowRevisionCreate(BaseModel):
    revision_label: str
    change_summary: Optional[str] = None


class WorkflowRevisionCloneRequest(BaseModel):
    revision_label: str
    change_summary: Optional[str] = None


class WorkflowRevisionOut(BaseModel):
    id: int
    workflow_id: int
    revision_label: str
    revision_number_sort: int
    status: str
    change_summary: Optional[str] = None
    supersedes_revision_id: Optional[int] = None
    created_by: Optional[str] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowStepCreate(BaseModel):
    step_type: str
    description: Optional[str] = None
    locator_strategy: Optional[str] = None
    locator_value: Optional[str] = None
    locator_fallbacks_json: Optional[str] = None
    locator_source: str = "MANUAL"
    input_value: Optional[str] = None
    is_sensitive: bool = False
    timeout_ms: Optional[int] = None
    expected_value: Optional[str] = None
    enabled: bool = True
    checkpoint_instructions: Optional[str] = None
    evidence_policy: str = "NONE"


class WorkflowStepUpdate(BaseModel):
    step_type: Optional[str] = None
    description: Optional[str] = None
    locator_strategy: Optional[str] = None
    locator_value: Optional[str] = None
    locator_fallbacks_json: Optional[str] = None
    locator_source: Optional[str] = None
    input_value: Optional[str] = None
    is_sensitive: Optional[bool] = None
    timeout_ms: Optional[int] = None
    expected_value: Optional[str] = None
    enabled: Optional[bool] = None
    checkpoint_instructions: Optional[str] = None
    evidence_policy: Optional[str] = None


class WorkflowStepOut(BaseModel):
    id: int
    revision_id: int
    sequence_no: int
    step_type: str
    description: Optional[str] = None
    locator_strategy: Optional[str] = None
    locator_value: Optional[str] = None
    locator_fallbacks_json: Optional[str] = None
    locator_source: str
    input_value: Optional[str] = None
    is_sensitive: bool
    timeout_ms: Optional[int] = None
    expected_value: Optional[str] = None
    enabled: bool
    checkpoint_instructions: Optional[str] = None
    evidence_policy: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowStepReorderRequest(BaseModel):
    step_ids_in_order: list[int]


class WorkflowTestCaseLinkCreate(BaseModel):
    test_case_id: int


class WorkflowTestCaseLinkOut(BaseModel):
    id: int
    workflow_revision_id: int
    test_case_id: int
    logical_case_key: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    # Flattened for the editor's link list.
    checkpoint_code: Optional[str] = None
    case_title: Optional[str] = None

    class Config:
        from_attributes = True
