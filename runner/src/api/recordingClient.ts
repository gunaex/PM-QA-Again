import type { RunnerConfig } from "../env.js";

export interface ClaimedSession {
  claimed: boolean;
  session?: { id: number; status: string; workflow_id: number; target_url: string };
  lease_token?: string;
}

export interface SessionDetail {
  id: number;
  status: string;
  cancel_requested?: boolean;
}

export interface PendingLocatorTestStep {
  id: number;
  locator_strategy: string | null;
  locator_value: string | null;
}

export class RecordingSessionClient {
  private base: string;
  private token: string;

  constructor(config: RunnerConfig) {
    this.base = `${config.backendBaseUrl}/api/${config.projectSlug}/recording-sessions`;
    this.token = config.runnerToken;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: {
        "X-Runner-Token": this.token,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${init.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
    }
    return (await res.json()) as T;
  }

  claim(): Promise<ClaimedSession> {
    return this.request<ClaimedSession>("/claim", { method: "POST" });
  }

  markStarted(sessionId: number, leaseToken: string): Promise<SessionDetail> {
    const qs = new URLSearchParams({ lease_token: leaseToken });
    return this.request<SessionDetail>(`/${sessionId}/recording-started?${qs.toString()}`, { method: "POST" });
  }

  getSession(sessionId: number): Promise<SessionDetail> {
    return this.request<SessionDetail>(`/${sessionId}`);
  }

  heartbeat(sessionId: number, leaseToken: string): Promise<SessionDetail> {
    return this.request<SessionDetail>(`/${sessionId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ lease_token: leaseToken }),
    });
  }

  appendStep(sessionId: number, leaseToken: string, step: Record<string, unknown>): Promise<{ id: number }> {
    return this.request(`/${sessionId}/steps`, {
      method: "POST",
      body: JSON.stringify({ ...step, lease_token: leaseToken }),
    });
  }

  pendingLocatorTests(sessionId: number, leaseToken: string): Promise<PendingLocatorTestStep[]> {
    const qs = new URLSearchParams({ lease_token: leaseToken });
    return this.request<PendingLocatorTestStep[]>(`/${sessionId}/pending-locator-tests?${qs.toString()}`);
  }

  submitLocatorTestResult(sessionId: number, stepId: number, leaseToken: string, result: { matchedCount: number; ok: boolean; message?: string }): Promise<unknown> {
    return this.request(`/${sessionId}/steps/${stepId}/locator-test-result`, {
      method: "POST",
      body: JSON.stringify({ matched_count: result.matchedCount, ok: result.ok, message: result.message, lease_token: leaseToken }),
    });
  }
}
