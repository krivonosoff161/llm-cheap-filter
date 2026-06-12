# Changelog

## [0.1.0] - 2026-06-12

### Added

- Offline triage pipeline with deterministic prefilter, cheap-stage scoring, and chief-stage escalation.
- Per-item report with filtered, cheap, chief, error, token, cost, and chief-rate summaries.
- CI test matrix for Ubuntu and Windows on Python 3.9, 3.11, and 3.12.
- Inline type marker (`py.typed`) and public callable aliases for injected LLM clients.

### Hardened

- Dedup normalizes survivor text before fuzzy comparison.
- Injected callable failures are isolated to per-item `error` results.
- Pipeline semaphore state is local to each `run()` call, so parallel runs on the same instance do not share mutable concurrency state.
