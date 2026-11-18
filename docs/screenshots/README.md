# Streamlit Approvals UI Screenshots

This directory contains visual previews of the Streamlit human-in-the-loop approvals interface for `lease-event-agent`.

---

### 1. Approvals Inbox (`01_approvals_inbox.png`)
![Approvals Inbox](01_approvals_inbox.png)

* **View Description:** Displays the real-time queue of commercial lease event notification memos awaiting human review.
* **Key Elements Visible:**
  * Urgency pill badges: `CRITICAL` (red, ≤60 days), `HIGH` (amber, 61–120 days), and `MEDIUM` (blue, 121–180 days).
  * Status filter controls: `Pending Approval`, `Approved`, `Rejected`, `Revision Requested`, and `All`.
  * Distinct adversarial injection demo badge (`DEMO`) isolating security test runs from production lease workflows.
  * Summary metrics: Pending queue count, approved volume, and high-urgency counts.

---

### 2. Cited Memo Detail & Document Passages (`02_cited_memo_detail.png`)
![Cited Memo Detail](02_cited_memo_detail.png)

* **View Description:** Deep-dive inspection into an extracted notification memo, linking every contractual claim to its source document passage.
* **Key Elements Visible:**
  * Extracted core lease metadata: Tenant name, asset name, holding SPV, event type, and passing rent with cross-register confirmation badges (`REGISTER CONFIRMED`).
  * Critical covenant analyses: Rent review mechanisms, tenant break conditions (vacant possession, arrears), reinstatement obligations, and estimated dilapidations liability.
  * Source passage citations: Expandable chunk containers showing exact page number, chunk ID (e.g. `LSE-EXP-001-p2-c1`), relevance score, and highlighting.
  * LLM extraction confidence gauge with low-confidence notifications warning if confidence falls below 0.60.

---

### 3. Human Decision Actions (`03_human_decision_actions.png`)
![Human Decision Actions](03_human_decision_actions.png)

* **View Description:** Action drawer enabling asset managers to authorize, reject, or request revisions on drafted memos.
* **Key Elements Visible:**
  * Reviewer identification input and approval submission button with optimistic locking protection against duplicate decisions (`409 Conflict`).
  * Rejection interface enforcing mandatory surveyor commentary and rationale documentation (`422 Unprocessable Entity` validation).
  * Revision request workflow prompting surveyor guidance; automatically supersedes previous run and re-queues the LangGraph agent with linked execution lineage.

---

### 4. Cryptographic Audit Log & Verification (`04_audit_ledger_verification.png`)
![Audit Ledger Verification](04_audit_ledger_verification.png)

* **View Description:** Tamper-evident, hash-chained ledger viewer verifying system integrity across every automated and human decision step.
* **Key Elements Visible:**
  * Real-time ledger status badge: `VALID (45 ENTRIES VERIFIED)` or alert indicating exact point of ledger tampering.
  * SHA-256 hash chaining columns displaying `Sequence ID`, `Timestamp (UTC)`, `Event Type` (`TRIGGER`, `RETRIEVE`, `INJECT_GUARD`, `INFER`, `VALIDATE`, `ROUTE`, `NOTIFY`, `HUMAN_DECISION`), `Run ID`, and `Entry Hash`.
  * Model governance and prompt tracking: Invariant prompt hashes (`prompt_hash`), input/output hashes, and model version identifiers recorded immutably.
  * Single-click JSON export for regulatory and compliance archiving.
