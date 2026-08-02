import { readFileSync, existsSync } from "node:fs";

// Deliberately no `dotenv` dependency — a spike stays small. Loads
// `.env` next to package.json if present; real env vars always win.
export function loadDotEnv(path = ".env"): void {
  if (!existsSync(path)) return;
  const contents = readFileSync(path, "utf-8");
  for (const rawLine of contents.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

export interface RunnerConfig {
  backendBaseUrl: string;
  projectSlug: string;
  runnerToken: string;
  targetBaseUrl: string;
  targetEmail: string;
  targetPassword: string;
}

export function loadConfig(): RunnerConfig {
  loadDotEnv();
  const required = (name: string): string => {
    const value = process.env[name];
    if (!value) {
      throw new Error(`Missing required env var ${name} (see .env.example)`);
    }
    return value;
  };
  return {
    backendBaseUrl: required("BACKEND_BASE_URL"),
    projectSlug: required("PROJECT_SLUG"),
    runnerToken: required("RUNNER_TOKEN"),
    // Execution workflows normally contain an absolute NAVIGATE URL.
    // These remain useful for the legacy spike, but cloud execution does
    // not need fake target credentials just to start.
    targetBaseUrl: process.env.TARGET_BASE_URL ?? "",
    targetEmail: process.env.TARGET_EMAIL ?? "",
    targetPassword: process.env.TARGET_PASSWORD ?? "",
  };
}
