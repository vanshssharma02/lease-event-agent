# Project Checklist: lease-event-agent

## Part 1: Foundation Layer
- [x] Environment configured with Python 3.11+
- [x] `.env.example`, `.gitignore`, `requirements.txt`, `README.md` created
- [x] Generic, synthetic data enforced (no real client names, no branding, no office locations)
- [x] Milestone 1: SQLite schema (`lease_register`, `asset_register`, `documents`), relative date seeding, 3 PDFs generated (including bilingual English/Arabic)
- [x] Milestone 2: Token-based PDF chunking, ChromaDB persistent indexing and typed retrieval
- [x] Milestone 3: Pydantic v2 schemas (`LeaseEventMemo`, `Cited*`), cross-register validator rules and truncations
- [x] Milestone 4: Slot-based `PromptBuilder`, `InjectionGuard` (threshold 0.75), and OpenRouter / mock `llm.py`
- [x] All 31 Part 1 tests passing

## Part 2: Orchestration, Audit, API & UI
### Milestone 5: Audit Log
- [x] `audit.py` with append-only hash-chained table `audit_log`
- [x] Genesis hash, canonical JSON SHA-256 computation, and exclusive locking
- [x] SQLite triggers blocking UPDATE and DELETE on `audit_log`
- [x] Functions: `append_entry()`, `get_run_trail()`, `export_all()`, `verify_chain()`
- [x] Acceptance check: tests for append, hash linkage, blocked modifications, and tamper detection

### Milestone 6: LangGraph Agent, Storage, Scheduler & Notifications
- [x] `agent.py`: LangGraph StateGraph (trigger -> retrieve -> injection_guard -> build_prompt -> infer -> validate -> route)
- [x] Hard error retry loop (max 2 retries) with error context feedback to prompt
- [x] Persistence tables: `agent_runs` and `inbox_items` in SQLite
- [x] `scheduler.py`: daily cron job + `python -m app.run` standalone runner
- [x] `notify.py`: email/local logging with `no_auto_notify` suppression on low confidence
- [x] Acceptance check: tests for happy path, retry loop, rejection on retry exhaustion, low-confidence routing, quarantine banner

### Milestone 7: FastAPI Backend
- [x] `api.py`: endpoints (`/agent/runs`, `/inbox`, `/inbox/{run_id}`, approve/reject/revise, `/audit`, `/demo/injection`, `/health`)
- [x] Validation: 409 conflict on double decision, 422 on missing comment for reject/revise, 404 on unknown runs
- [x] Demo injection generator for live demo testing
- [x] Acceptance check: API tests with FastAPI TestClient

### Milestone 8: Streamlit UI & Smoke Test
- [x] `ui/streamlit_app.py`: Inbox view, Memo detail with cited text highlighting, Red quarantine banner, decision buttons, Audit trail verification
- [x] `scripts/smoke_test.py` end-to-end automated runner
- [x] Acceptance check: all tests pass + smoke test completes successfully

## Part 3: Review Bug Fixes, Evaluation & Packaging
### Milestone 9: Bug Fixes & Isolation (Review Findings)
- [x] **Deduplication:** Shared `check_active_event_exists` skips leases with `pending_approval` or `approved` item for same lease, event type, and date across scheduler, `app.run`, and `POST /agent/runs`.
- [x] **Revision Supersede:** `/inbox/{run_id}/revise` marks old item `revision_requested` and links new run via `parent_run_id`.
- [x] **Force Override:** `force: true` allows manual re-run bypassing deduplication.
- [x] **Demo Isolation:** `LSE-DEMO-INJ-001` excluded from `get_leases_in_window` and batch runs; flagged `is_demo=1` in register; displayed with `DEMO` badge in UI; endpoint is idempotent.
- [x] **Smoke Test Isolation:** `scripts/smoke_test.py` executes against temporary DB, Chroma directory, and audit log; asserts exactly 3 pending items after 1st trigger and 0 new items after 2nd trigger.
- [x] **Milestone 9 Tests:** Dedicated unit/integration tests in `tests/test_milestone9.py` passing.

### Milestone 10: Evaluation Harness
- [x] `eval/golden.json`: Dynamic relative ground truth for seeded in-window leases.
- [x] `eval/injection_cases.json`: 28 labelled chunks (14 injected across all attack vectors + 14 benign including tricky legal phrasing).
- [x] `eval/run_eval.py`: Benchmark harness computing extraction accuracy, citation validity, schema-pass rate, retries, rejection rate, guard confusion matrix (precision, recall, FPR), and latencies.
- [x] Generated artifacts: `eval/results.json` and `eval/RESULTS.md`.
- [x] `tests/test_eval.py`: Evaluation unit tests passing.

### Milestone 11: GitHub Packaging
- [x] `Dockerfile` and `docker-compose.yml` for unified container deployment
- [x] `tasks.ps1` PowerShell task runner and `Makefile` for multi-platform developer ergonomics
- [x] Pinned `requirements.txt` and `requirements-dev.txt`
- [x] `.github/workflows/ci.yml` matrix CI pipeline
- [x] `docs/screenshots/README.md`
- [x] `scripts/live_check.py` OpenRouter connectivity verification utility
- [ ] Comprehensive `README.md` (with two Mermaid diagrams, benchmark numbers, design decisions, roadmap)
- [ ] `LICENSE` (MIT) and `CONTRIBUTING.md`
- [ ] Final repo-wide safety scan for forbidden strings and credentials

---

## Server Startup Instructions (Windows)

To start both servers locally in two separate PowerShell terminals:

1. **Terminal 1: Start FastAPI Backend**
   ```powershell
   python -m uvicorn app.api:app --reload --port 8000
   ```
   API Docs available at: `http://localhost:8000/docs`

2. **Terminal 2: Start Streamlit Approvals Inbox UI**
   ```powershell
   python -m streamlit run ui/streamlit_app.py
   ```
   UI Dashboard available at: `http://localhost:8501`

3. **Standalone End-to-End Smoke Test**
   ```powershell
   python scripts/smoke_test.py
   ```
