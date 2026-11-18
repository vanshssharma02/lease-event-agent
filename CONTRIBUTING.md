# Contributing to lease-event-agent

Contributions and bug reports are welcome.

## Workflow
1. Fork the repo and create a feature branch.
2. Keep all data synthetic and generic (never commit .env, .db, or .pdf files).
3. Run python -m pytest, python scripts/smoke_test.py, and python -m eval.run_eval --mode mock before opening a PR.
