# VektorDeck Roadmap

## 1.0 — Completed product scope

VektorDeck 1.0 completes the first Windows local-workstation release.

The finished scope includes:

- local GGUF/checkpoint discovery and SQLite indexing
- safe llama.cpp / AUTOMATIC1111 / Hermes runtime control
- persistent launch profiles and default-profile management
- live CPU/RAM/GPU/VRAM telemetry
- runtime ownership recovery and external-process protection
- bounded GGUF Model Intelligence and projector pairing
- profile readiness checks and launch-command previews
- benchmark evidence with explicit quality classification
- Benchmark Protocol v2 with quiet-baseline provenance
- read-only benchmark contamination diagnostics
- Smart Launch experimental vs evidence-backed recommendations
- hardware-aware Memory Optimizer experiments
- Release Readiness installation checks
- one-click Start / Stop / Update / Repair / Diagnostics workflow
- dependency-aware self-restarting updater
- GitHub Actions backend/frontend quality gates
- local regression/build validation
- live post-relaunch smoke validation

## Evidence policy

Performance evidence is intentionally independent from product correctness.

Only controlled Protocol-v2 evidence with a recorded quiet baseline can promote Smart Launch recommendations. Legacy, pressured, unverified, or contaminated runs may remain as history but cannot become trusted winners.

If the workstation cannot reach a clean baseline, performance validation remains `PENDING`. This is an honest release state, not a reason to fabricate a benchmark or weaken the baseline thresholds.

## Post-1.0

The following are intentionally outside the completed 1.0 scope:

- packaged desktop installer
- ComfyUI adapter
- remote/mobile control
- plugin architecture
- broader model-runtime/vendor support
- additional hardware-specific tuning labs

These are optional future extensions rather than unfinished release requirements.
