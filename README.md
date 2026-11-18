# lease-event-agent

An LLM-powered, human-in-the-loop agent that monitors a commercial lease register, drafts cited notification memos for upcoming lease events (expiry, break option, rent review), and routes them to an approvals inbox with a tamper-evident audit log.

## Status: Part 1 of 3 (Foundation Layer)

Part 1 implements the core foundation:
- **Data Layer**: SQLite database (`lease_register`, `asset_register`, `documents`), synthetic data generator with relative dates, and synthetic multi-page PDF lease agreements.
- **Retrieval**: Token-aware PDF chunking with stable chunk IDs and page tracking, indexed in persistent ChromaDB.
- **Schema & Validation**: Pydantic v2 schemas (`LeaseEventMemo`, `CitedStr`, `CitedMoney`, `CitedDate`) and deterministic cross-register consistency validators.
- **Prompt & Injection Guard**: Modular slot-based prompt builder and multi-vector prompt injection quarantine guard.
- **LLM Client**: OpenRouter-compatible client with exponential backoff, model fallback, and deterministic mock generator.

Later parts will introduce:
- Part 2: LangGraph workflow orchestration, human-in-the-loop approvals, and tamper-evident audit log.
- Part 3: FastAPI REST backend and Streamlit UI dashboard.
