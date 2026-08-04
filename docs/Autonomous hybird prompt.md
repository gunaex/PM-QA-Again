# QA-Again — Autonomous Hybrid MVP Delivery

## HYB-1 through HYB-5, Sequentially Gated

Proceed autonomously through the approved Hybrid Manual + Automation MVP roadmap.

This is one continuous delivery assignment, but it is not one uncontrolled implementation batch.

Implement HYB-1, HYB-2, HYB-3, HYB-4, and HYB-5 strictly in sequence.

You may continue automatically to the next HYB phase only when:

* the current phase's acceptance criteria pass;
* backend tests pass;
* the frontend production build passes;
* the required real-browser verification passes;
* ROADMAP.md and relevant documentation are updated;
* the phase is committed and pushed separately;
* no unresolved architectural or data-integrity blocker remains.

If a phase fails its gate, stop at that phase and report concrete evidence. Do not build later phases on an unverified foundation.

Do not wait for routine approval between successful phases.

---

# Preflight — Required before HYB-1

Before hybrid feature work:

1. Confirm that the performance fast pass is complete, committed, and pushed.
2. Run `git status` and confirm the working tree is clean.
3. Record:

   * current branch;
   * current commit;
   * current backend test count;
   * current frontend build status.
4. Confirm Track A remains operational.
5. Confirm the current release-readiness status and unresolved release blockers.
6. Do not falsely mark the system production-ready.
7. Create a stable Track A baseline tag before hybrid implementation begins.
8. Create a dedicated hybrid feature branch from that baseline.
9. Do not force-push or rewrite existing history.
10. Refresh the HYB-0 gap analysis against the final Track A implementation.

The refreshed analysis must account for the completed:

* test suites and immutable revisions;
* test cycles and execution;
* cycle-result history;
* evidence capture and annotation;
* EvidenceStorage abstraction;
* filesystem and R2 storage implementations;
* authentication and role authorization;
* CSRF and CORS protections;
* audit/activity history;
* dashboard and reports;
* Excel and ZIP exports;
* existing hybrid extension fields;
* performance changes introduced by the latest fast pass.

Write the refreshed analysis before HYB-1 feature code.

---

# Global Hybrid Principles

These rules apply to every HYB phase.

## Trust model

* AI may draft workflows, locators, descriptions, and expected results.
* AI must never issue the final human PASS/FAIL/BLOCKED/N/A decision.
* Human decisions and machine assertions must remain distinguishable.
* Never convert a human FAIL into PASS automatically.
* Never report a machine step as successful without a real execution result.
* Every result must carry actor type, actor identity where applicable, timestamp, source, and execution context.
* Preserve append-only execution and decision history.

## Architecture

* FastAPI remains the control plane.
* The browser runner remains a separate Node.js + TypeScript + Playwright process.
* Do not embed Playwright inside the public FastAPI process.
* Runner communication remains outbound-only from runner to control plane.
* Do not require inbound firewall access to the runner.
* Frontend remains React + Vite.
* SQLite remains the current metadata database architecture.
* Evidence continues through EvidenceStorage.
* R2 remains private.
* Track A manual execution remains fully supported.

## Recorder safety

* Do not record global operating-system mouse or keyboard activity.
* Record only actions within a controlled Playwright browser session.
* Do not depend on raw X/Y coordinates as the primary locator.
* Never persist real passwords, tokens, OTP values, card data, or secrets.
* Sensitive values must become named variables or secret placeholders.
* Do not capture hidden or masked values from password inputs.
* Do not record browser cookies or authorization headers.
* Do not allow arbitrary JavaScript execution in the MVP.
* Branching, loops, arbitrary scripting, and autonomous locator repair remain out of scope.

## Existing invariants

Preserve:

* immutable published revisions;
* immutable original evidence;
* append-only annotation revisions;
* append-only result history;
* cycle locking;
* admin reopen rules;
* evidence-required-for-PASS policy;
* N/A approval requirements;
* quota enforcement;
* MIME validation;
* CSRF protection;
* authorization;
* audit logging;
* export integrity.

Do not weaken these rules to make automation easier.

---

# HYB-1 — Workflow Model and Editor

## Objective

Create the durable, reviewable workflow format that the runner and recorder will use.

The workflow system must support:

* workflow definitions;
* immutable published workflow revisions;
* editable drafts;
* clone-for-correction;
* workflow steps;
* test-case links;
* manual checkpoints;
* variables and secret references;
* validation;
* frontend editing and review.

## Domain model

Implement entities equivalent to:

### WorkflowDefinition

Suggested responsibilities:

* stable workflow identity;
* project ownership;
* name;
* description;
* status;
* current published revision reference;
* creator and timestamps;
* archive state.

### WorkflowRevision

Suggested responsibilities:

* revision number;
* DRAFT, PUBLISHED, or SUPERSEDED state;
* immutable after publish;
* clone source;
* change summary;
* created by;
* published by;
* timestamps.

### WorkflowStep

Support an ordered step sequence.

Initial MVP step types should include:

* NAVIGATE;
* CLICK;
* FILL;
* SELECT;
* CHECK;
* UNCHECK;
* PRESS_KEY;
* WAIT_FOR_ELEMENT;
* ASSERT_VISIBLE;
* ASSERT_TEXT;
* ASSERT_URL;
* SCREENSHOT;
* MANUAL_CHECKPOINT.

Do not add branching or loops.

Each step should support only fields meaningful to its type.

Include:

* sequence number;
* step type;
* user-facing description;
* locator strategy;
* locator payload;
* input value or variable reference;
* timeout;
* expected value;
* sensitive flag;
* enabled state;
* checkpoint configuration;
* evidence policy;
* metadata needed for provenance.

### WorkflowTestCaseLink

Allow a workflow revision to link to one or more Track A test cases without altering the immutable test-script revision.

Define explicitly whether links point to:

* stable test-case identity;
* exact test-case revision snapshot;
* or both.

Do not silently choose a behavior that breaks historical reproducibility.

## Locator format

Use a structured locator model rather than storing arbitrary Playwright source code.

Preferred locator priority:

1. `data-testid` or explicit automation identifier.
2. Accessible role and accessible name.
3. Associated label.
4. Placeholder or stable semantic attribute.
5. Stable text where appropriate.
6. CSS fallback.
7. XPath only as a last-resort fallback.

A locator may contain:

* primary strategy;
* primary value;
* fallback candidates;
* page/context hint;
* confidence or warning state;
* source: MANUAL, RECORDER, or IMPORTED.

Raw coordinates are not a valid primary locator.

## Workflow editor

Build a real frontend editor supporting:

* workflow list;
* create workflow;
* draft revision;
* ordered step list;
* add/edit/delete/reorder steps;
* step-type-specific fields;
* locator editor;
* variable references;
* sensitive-value handling;
* manual-checkpoint editor;
* validation summary;
* publish;
* clone published revision for correction;
* link to test cases;
* revision history.

Publishing must reject invalid workflows.

## HYB-1 acceptance gate

Verify:

1. Create workflow definition.
2. Create draft revision.
3. Add all supported MVP step types.
4. Reorder steps.
5. Configure a manual checkpoint.
6. Configure a sensitive variable without persisting its real value.
7. Link workflow to a test case.
8. Publish revision.
9. Confirm published revision cannot be edited.
10. Clone it into a new draft.
11. Confirm old revisions remain unchanged.
12. Confirm authorization boundaries.
13. Confirm audit/activity records.
14. Verify through API tests and a real headed-browser UI flow.

Update documentation, ROADMAP.md, tests, commit, and push.

Do not start HYB-2 unless all HYB-1 gates pass.

---

# HYB-2 — Runner Registration and Execution

## Objective

Build the real runner service and reliable execution protocol.

## Runner identity

Implement:

* runner registration;
* generated runner ID;
* revocable runner credential;
* project or environment scope;
* runner name;
* version;
* operating-system metadata;
* browser version;
* capabilities;
* last heartbeat;
* online/offline/stale/revoked status.

Store runner credentials securely.

Do not expose runner secrets in the frontend after initial provisioning.

## Runner communication

The runner must communicate outbound to FastAPI.

Implement a safe job protocol such as:

1. Runner authenticates.
2. Runner sends heartbeat.
3. Runner requests or claims an available job.
4. Server grants a time-limited lease.
5. Runner renews the lease while working.
6. Runner sends structured step events.
7. Runner uploads evidence.
8. Runner sends terminal run status.

Prevent two runners from executing the same leased job simultaneously.

Handle:

* expired leases;
* revoked runner credentials;
* duplicate event delivery;
* retry after network interruption;
* stale runner detection;
* job cancellation;
* safe requeue rules.

Use idempotency keys for retryable runner events.

## Execution model

Implement entities equivalent to:

* WorkflowRun;
* WorkflowStepRun;
* RunnerEvent;
* RunnerLease;
* RunHistory.

Run status should include states such as:

* QUEUED;
* CLAIMED;
* STARTING;
* RUNNING;
* PAUSED;
* WAITING_FOR_HUMAN;
* RESUMING;
* PASSED;
* FAILED;
* BLOCKED;
* CANCELLED;
* RUNNER_LOST;
* SYSTEM_ERROR.

Document allowed state transitions.

Reject invalid transitions.

## Step execution

Execute published workflow revisions through Playwright.

Do not execute drafts.

For every step record:

* workflow revision;
* step identity;
* sequence;
* runner identity;
* start time;
* end time;
* elapsed time;
* attempt number;
* outcome;
* failure category;
* machine message;
* locator actually used;
* screenshot/evidence references where applicable.

Failure categories should distinguish at minimum:

* LOCATOR_NOT_FOUND;
* LOCATOR_AMBIGUOUS;
* TIMEOUT;
* NAVIGATION_ERROR;
* ASSERTION_FAILED;
* INPUT_ERROR;
* BROWSER_CRASH;
* RUNNER_DISCONNECTED;
* CANCELLED;
* SYSTEM_ERROR.

Do not report an assertion failure as a system error or vice versa.

## Browser session

A workflow run must use one persistent browser context/session unless the workflow explicitly starts a new one.

Preserve the same browser session across pauses and resumptions.

## HYB-2 frontend

Build UI for:

* runner list;
* runner registration instructions;
* runner status;
* revoke runner;
* workflow-run creation;
* queued/running/completed runs;
* live structured step status;
* cancellation;
* failure details;
* run history.

## HYB-2 acceptance gate

Verify with a real Node/TypeScript runner and visible Chromium:

1. Register runner.
2. Heartbeat appears.
3. Queue a published workflow.
4. Runner claims the job.
5. Execute multiple real semantic-locator steps.
6. Record structured step results.
7. Upload screenshot evidence.
8. Complete run.
9. Retry one duplicate event and confirm idempotency.
10. Revoke a runner and confirm it can no longer claim work.
11. Simulate runner loss.
12. Confirm state becomes RUNNER_LOST or the documented equivalent.
13. Confirm no duplicate job execution.
14. Confirm human and runner provenance remain distinct.
15. Confirm all Track A tests still pass.

Update documentation, ROADMAP.md, tests, commit, and push.

Do not start HYB-3 unless all HYB-2 gates pass.

---

# HYB-3 — Browser Workflow Recorder

## Objective

Allow a tester to perform a browser flow once and generate a reviewable draft workflow.

This is the phase that adds the requested mouse and keyboard recording capability.

## Recording boundary

Recording must occur only inside a controlled browser session launched or attached by the QA Runner.

Do not create a global desktop keylogger or mouse recorder.

Capture semantic browser actions rather than arbitrary OS events.

## Supported recorded actions

Record at minimum:

* page navigation;
* link click;
* button click;
* textbox fill;
* textarea fill;
* select/dropdown change;
* checkbox check/uncheck;
* radio selection;
* keyboard shortcut relevant to the page;
* form submission;
* tab or page change where supported;
* file-upload intent without storing the original private local path;
* explicit screenshot request;
* tester-inserted manual checkpoint.

Do not record insignificant mouse movement.

Do not create a workflow step for every raw keypress when a complete field value can be represented as one FILL action.

## Semantic locator capture

For each interaction, collect candidate locators from the target DOM element.

Generate a ranked locator set using:

1. explicit test ID;
2. role and accessible name;
3. label;
4. stable semantic attributes;
5. stable text;
6. CSS fallback.

Store:

* selected primary locator;
* fallback locators;
* locator quality warnings;
* page URL or route context;
* target element summary;
* whether uniqueness was verified at recording time.

Do not rely on screen coordinates except optional diagnostic metadata.

## Sensitive input handling

Detect common sensitive fields using:

* input type;
* autocomplete attribute;
* name;
* label;
* ARIA metadata;
* configured sensitive patterns.

For sensitive fields:

* never persist the actual value;
* generate a variable placeholder;
* mark the variable as secret;
* display a clear warning;
* require runtime secret injection.

Examples:

```text
${SECRET_LOGIN_PASSWORD}
${OTP_CODE}
${CUSTOMER_TOKEN}
```

Do not store secret values in logs, screenshots, exported workflow JSON, or run events.

## Noise reduction

The recorder should merge or simplify actions where safe.

Examples:

* multiple key events in one input become one FILL step;
* click followed by form navigation should not produce meaningless duplicate navigation steps;
* repeated focus events should be ignored;
* accidental double-clicks should be represented deliberately, not duplicated automatically;
* browser-generated events should not become user steps.

Do not silently remove actions when doing so could alter behavior.

Flag uncertain simplifications for tester review.

## Recorder UI

Build:

* Start Recording;
* Pause Recording;
* Resume Recording;
* Stop Recording;
* live recorded-step list;
* step deletion;
* step editing;
* locator warning display;
* sensitive-field warning;
* add manual checkpoint;
* test a selected locator;
* save as workflow draft;
* discard recording.

Stopping recording must create a DRAFT workflow revision, never publish automatically.

The tester must review and publish manually.

## HYB-3 acceptance gate

Use a real headed Chromium session.

Record a realistic flow containing:

1. navigation;
2. text input;
3. sensitive password input;
4. button click;
5. dropdown selection;
6. checkbox or radio action;
7. page transition;
8. manual checkpoint insertion.

Then verify:

* no raw password was persisted;
* no global keyboard data was captured;
* no irrelevant mouse movement became steps;
* locators are semantic;
* warnings appear for weak locators;
* the draft can be edited;
* the draft can be published;
* the published workflow can be executed by HYB-2;
* the replay succeeds against the same application;
* a layout-only position change does not break a semantic locator;
* failure output is honest when a target genuinely no longer exists.

Update documentation, ROADMAP.md, tests, commit, and push.

Do not start HYB-4 unless all HYB-3 gates pass.

---

# HYB-4 — Hybrid Manual Checkpoints and Evidence

## Objective

Allow automated execution to pause for human verification and resume within the same browser session.

## Checkpoint behavior

When the runner reaches `MANUAL_CHECKPOINT`:

1. Complete all prior machine steps.
2. Keep the browser context and page alive.
3. Capture checkpoint context.
4. Move the run to WAITING_FOR_HUMAN.
5. Show the checkpoint in the QA-Again UI.
6. Display:

   * workflow;
   * case;
   * current step;
   * expected result;
   * browser screenshot;
   * prior machine assertions;
   * evidence;
   * runner status.
7. Allow an authorized human to:

   * PASS;
   * FAIL;
   * BLOCK;
   * mark N/A only where the existing policy permits;
   * add actual result;
   * add reason;
   * capture/upload evidence;
   * annotate evidence;
   * create/link a defect.
8. Record human identity and timestamp.
9. Resume only when the decision permits it.
10. Continue using the same browser session.

A human FAIL must not become an automatic PASS because later machine steps succeeded.

## Pause safety

Implement:

* checkpoint lease or ownership;
* protection against two testers deciding simultaneously;
* explicit decision revision/history;
* double-submit protection;
* runner heartbeat while paused;
* maximum pause policy;
* cancellation;
* runner-lost behavior;
* server-restart recovery behavior.

Do not pretend that an in-memory browser session survived if the runner process actually died.

If the session is lost:

* mark the run honestly;
* preserve completed step history;
* preserve human decisions and evidence;
* allow a documented restart or rerun path;
* never fabricate continuation.

## Evidence integration

Reuse Track A evidence behavior.

Evidence must be linked to:

* project;
* workflow run;
* step run or checkpoint;
* cycle result where linked;
* actor;
* source;
* timestamp.

Preserve immutable original files and append-only annotations.

## Defect linkage

Allow defects created at a checkpoint to reference:

* workflow run;
* workflow revision;
* step;
* checkpoint;
* related cycle result;
* evidence.

## HYB-4 acceptance gate

Verify with a real browser and real human-operated UI:

1. Start hybrid workflow.
2. Execute automated steps.
3. Pause at manual checkpoint.
4. Confirm browser session remains alive.
5. Add evidence.
6. Annotate it.
7. Make a human PASS decision.
8. Resume and complete.
9. Repeat with human FAIL.
10. Confirm later automation cannot overwrite FAIL.
11. Repeat with BLOCKED.
12. Simulate runner disconnection while paused.
13. Confirm honest lost-runner handling.
14. Confirm double-decision conflict protection.
15. Confirm locked Track A cycles preserve their mutation rules.
16. Confirm actor provenance in UI, API, history, reports, Excel, and ZIP where applicable.

Update documentation, ROADMAP.md, tests, commit, and push.

Do not start HYB-5 unless all HYB-4 gates pass.

---

# HYB-5 — Timing, Reports, Recovery, and Hardening

## Objective

Complete the Hybrid MVP with timing history, reporting, exports, security hardening, recovery behavior, and handover.

## Timing history

Record per-step timing:

* queue delay;
* runner claim delay;
* browser startup;
* step start/end;
* step duration;
* checkpoint wait duration;
* resume delay;
* evidence-upload duration;
* total run duration.

Preserve historical runs.

Do not reduce timing to only PASS/FAIL.

Provide trend views such as:

```text
Save Customer

Run 1: 1.2 seconds
Run 2: 1.5 seconds
Run 3: 2.8 seconds
```

Do not make AI the final authority on whether a timing change is acceptable.

Allow users to view the difference and decide.

## Reports

Add hybrid reporting for:

* workflow-run status;
* machine step outcomes;
* human checkpoint decisions;
* machine-versus-human provenance;
* locator failure frequency;
* runner reliability;
* step timing history;
* checkpoint waiting time;
* evidence completeness;
* failure categories;
* run trends.

Do not modify existing Track A formulas silently.

## Exports

Update Excel and portable ZIP exports to include hybrid data.

Include:

* workflow definition;
* exact workflow revision;
* workflow steps;
* runner identity;
* run status;
* step results;
* timings;
* human checkpoint decisions;
* evidence;
* annotation revisions;
* defects;
* actor provenance;
* event timestamps;
* manifest references.

Use EvidenceStorage to retrieve files.

Do not substitute presigned URLs for real files in portable exports.

## Security

Write:

```text
docs/HYBRID_RUNNER_THREAT_MODEL.md
```

Cover at minimum:

* runner credential theft;
* revoked runner reuse;
* malicious runner events;
* replayed events;
* duplicate job execution;
* job theft;
* lease expiry;
* fake PASS events;
* secret leakage;
* recorder keylogging risk;
* sensitive input handling;
* screenshot leakage;
* untrusted target pages;
* browser compromise;
* SSRF/navigation restrictions where applicable;
* malicious file upload;
* event tampering;
* unauthorized checkpoint decisions;
* runner-to-project isolation;
* lost-runner recovery.

Add tests supporting material claims.

## Recovery and operations

Document:

* runner installation;
* registration;
* upgrade;
* revocation;
* credential rotation;
* browser dependency installation;
* runner health diagnosis;
* stale runner cleanup;
* lost-run recovery;
* stuck job recovery;
* event reconciliation;
* evidence reconciliation;
* safe retry;
* cancellation;
* backups;
* rollback.

## User guides

Write guides for:

* administrator;
* workflow author;
* tester;
* runner operator;
* checkpoint reviewer.

## Performance

Test realistic workflow sizes.

At minimum test:

* workflow with 50+ steps;
* multiple sequential runs;
* long manual pause;
* evidence-heavy run;
* runner disconnect;
* repeated locator failure;
* dashboard/report load with historical run data.

Cloud-scale parallel browser farms remain out of scope.

## HYB-5 acceptance gate

Verify:

1. Timing history persists.
2. Trend UI works.
3. Reports distinguish machine and human results.
4. Excel export includes hybrid records.
5. ZIP manifest links every hybrid artifact correctly.
6. Security tests pass.
7. Runner recovery procedures are exercised.
8. Clean-environment installation is rehearsed.
9. Full backend suite passes.
10. Frontend production build passes.
11. Runner build and tests pass.
12. Real headed-browser hybrid workflow passes.
13. Documentation and handover are complete.
14. No existing Track A workflow regresses.

Update ROADMAP.md, commit, and push.

---

# Required Version-Control Discipline

Use one or more reviewable commits per HYB phase.

At minimum, produce distinct phase completion commits:

* HYB-1 complete;
* HYB-2 complete;
* HYB-3 complete;
* HYB-4 complete;
* HYB-5 complete.

After each phase:

1. Review the complete diff.
2. Run tests.
3. Run frontend build.
4. Run runner build/tests when applicable.
5. Verify no secrets.
6. Verify no local databases.
7. Verify no evidence files.
8. Verify no `.venv`.
9. Verify no `node_modules`.
10. Verify no build artifacts unless intentionally tracked.
11. Update ROADMAP.md.
12. Commit.
13. Push.
14. Record the commit hash.

Do not squash all HYB phases into one final commit.

Do not force-push.

Create phase tags only if consistent with the repository's current tagging convention.

---

# Required Final Report

After HYB-5, report:

## Phase results

For each HYB phase:

* scope delivered;
* acceptance criteria;
* tests;
* real-browser evidence;
* bugs found;
* architectural decisions;
* commit hash.

## Final architecture

Describe:

* FastAPI control plane;
* React frontend;
* QA Runner;
* workflow lifecycle;
* recorder;
* job protocol;
* checkpoint flow;
* evidence flow;
* result provenance;
* timing and reports.

## Verification totals

Report separately:

* backend test count;
* frontend build;
* runner tests;
* Playwright/browser verification;
* export inspection;
* security tests;
* clean-environment rehearsal.

## Known limitations

Preserve and report actual MVP limitations, including:

* no branching or loops;
* no arbitrary scripting;
* no autonomous AI sign-off;
* no automatic Git-diff impact analysis;
* no IDE integration;
* no cloud browser farm;
* no mobile/desktop automation;
* no continuous video;
* no autonomous locator repair;
* no pixel-diff final authority.

## Release status

Do not mark the system production-ready unless all Track A release blockers and all Hybrid MVP release gates have genuinely passed.

Use one final status:

* `HYBRID MVP COMPLETE — PRODUCTION READY`
* `HYBRID MVP COMPLETE — NOT PRODUCTION READY`
* `HYBRID MVP INCOMPLETE — BLOCKED AT HYB-X`

Include exact blockers and evidence.

---

# Stop Conditions

Stop at the current HYB phase and report instead of taking a risky shortcut if:

* a destructive database migration is required;
* existing Track A data may be lost;
* runner architecture would require exposing an unsafe inbound service;
* authentication or authorization would be weakened;
* human and machine provenance cannot remain distinct;
* evidence immutability would be broken;
* secrets would need to be persisted;
* global keyboard/mouse recording would be required;
* automated tests cannot validate a critical invariant;
* the real-browser acceptance gate fails;
* later HYB work would depend on an unresolved earlier failure.

Ordinary local, well-understood, testable defects should be fixed and documented.

Do not stop merely because the task is large.

---

# Final instruction

Complete the preflight and refreshed gap analysis first.

Then implement HYB-1 through HYB-5 sequentially.

Continue automatically after each successful phase.

Never skip a gate.

Never describe mocked output as real runner execution.

Never store real sensitive values from the recorder.

Never allow AI or later machine steps to overwrite a human decision.

Commit and push every completed phase separately.

Return only after HYB-5 is complete or a genuine stop condition is reached.
