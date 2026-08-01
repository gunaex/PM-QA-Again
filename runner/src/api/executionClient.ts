import type { RunnerConfig } from "../env.js";

// HYB-2 job-claim protocol client. Every call here is outbound, exactly
// like the HYB-0 spike's client.ts -- the backend never calls into the
// runner. See backend/app/routers/workflow_runs.py for the exact
// contract this implements.

export type WorkflowRunStatus =
  | "QUEUED" | "CLAIMED" | "STARTING" | "RUNNING" | "PAUSED" | "WAITING_FOR_HUMAN"
  | "RESUMING" | "PASSED" | "FAILED" | "BLOCKED" | "CANCELLED" | "RUNNER_LOST" | "SYSTEM_ERROR";

export interface ClaimedStep {
  id: number;
  sequence_no: number;
  step_type: string;
  description: string | null;
  locator_strategy: string | null;
  locator_value: string | null;
  locator_fallbacks_json: string | null;
  input_value: string | null;
  is_sensitive: boolean;
  timeout_ms: number | null;
  expected_value: string | null;
  checkpoint_instructions: string | null;
  evidence_policy: string;
}

export interface ClaimedRun {
  claimed: boolean;
  run?: { id: number; status: WorkflowRunStatus; cancel_requested: boolean };
  steps?: ClaimedStep[];
  lease_token?: string;
  target_base_url?: string | null;
}

export interface RunDetail {
  id: number;
  status: WorkflowRunStatus;
  cancel_requested: boolean;
}

export class WorkflowRunClient {
  private base: string;
  private token: string;

  constructor(config: RunnerConfig) {
    this.base = `${config.backendBaseUrl}/api/${config.projectSlug}/workflow-runs`;
    this.token = config.runnerToken;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: {
        "X-Runner-Token": this.token,
        ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${init.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
    }
    return (await res.json()) as T;
  }

  claim(): Promise<ClaimedRun> {
    return this.request<ClaimedRun>("/claim", { method: "POST" });
  }

  heartbeat(runId: number, leaseToken: string): Promise<RunDetail> {
    return this.request<RunDetail>(`/${runId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ lease_token: leaseToken }),
    });
  }

  getRun(runId: number): Promise<RunDetail> {
    return this.request<RunDetail>(`/${runId}`);
  }

  postEvent(runId: number, leaseToken: string, eventType: string, opts: { idempotencyKey?: string; actorType?: string; payload?: unknown } = {}): Promise<unknown> {
    return this.request(`/${runId}/events`, {
      method: "POST",
      body: JSON.stringify({
        event_type: eventType,
        actor_type: opts.actorType ?? "RUNNER",
        idempotency_key: opts.idempotencyKey,
        payload_json: opts.payload ? JSON.stringify(opts.payload) : undefined,
        lease_token: leaseToken,
      }),
    });
  }

  startStepRun(runId: number, leaseToken: string, workflowStepId: number, attemptNumber = 1): Promise<{ id: number }> {
    return this.request(`/${runId}/step-runs`, {
      method: "POST",
      body: JSON.stringify({ workflow_step_id: workflowStepId, attempt_number: attemptNumber, lease_token: leaseToken }),
    });
  }

  finishStepRun(
    runId: number,
    stepRunId: number,
    leaseToken: string,
    result: { status: "PASSED" | "FAILED" | "SKIPPED"; outcome?: string; failureCategory?: string; machineMessage?: string; locatorUsedJson?: string },
  ): Promise<unknown> {
    return this.request(`/${runId}/step-runs/${stepRunId}`, {
      method: "PUT",
      body: JSON.stringify({
        status: result.status,
        outcome: result.outcome,
        failure_category: result.failureCategory,
        machine_message: result.machineMessage,
        locator_used_json: result.locatorUsedJson,
        lease_token: leaseToken,
      }),
    });
  }

  async uploadEvidence(runId: number, leaseToken: string, stepRunId: number | undefined, fileBuffer: Buffer, filename: string): Promise<unknown> {
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array(fileBuffer)], { type: "image/png" }), filename);
    const qs = new URLSearchParams({ lease_token: leaseToken });
    if (stepRunId !== undefined) qs.set("step_run_id", String(stepRunId));
    return this.request(`/${runId}/evidence?${qs.toString()}`, { method: "POST", body: form });
  }

  complete(runId: number, leaseToken: string, status: "PASSED" | "FAILED" | "BLOCKED" | "SYSTEM_ERROR" | "CANCELLED", resultSummary?: string): Promise<unknown> {
    return this.request(`/${runId}/complete`, {
      method: "POST",
      body: JSON.stringify({ status, result_summary: resultSummary, lease_token: leaseToken }),
    });
  }
}
