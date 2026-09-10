# Changelog

## 1.0.0

VektorDeck 1.0 completes the first Windows local-workstation product scope.

### Added

- local GGUF and checkpoint discovery with SQLite indexing
- bounded GGUF metadata inspection with cached model intelligence
- projector pairing hints and profile readiness checks
- safe llama.cpp, AUTOMATIC1111, and Hermes runtime control
- loopback-only profile safety and external-process protection
- persistent llama.cpp ownership leases and validated recovery
- live CPU, RAM, GPU, and VRAM telemetry
- benchmark evidence with HEALTHY / TIGHT / PRESSURED / UNVERIFIED quality states
- Benchmark Protocol v2 with quiet-baseline provenance and contaminator snapshots
- Smart Launch recommendations with explicit experimental vs evidence-backed states
- hardware-aware Memory Optimizer experiments gated by quiet-workstation preflight
- read-only process contamination inspector
- Release Readiness drawer for daily-use installation checks
- one-click Windows Start / Stop / Update / Repair / Diagnostics workflow
- self-restarting updater when the updater itself changes during pull
- dependency-aware updater refreshes
- live post-relaunch smoke validation
- GitHub Actions backend/frontend CI

### Changed

- benchmark recommendations now exclude legacy, pressured, unverified, and contaminated evidence
- Smart Launch promotion requires repeated controlled Protocol-v2 evidence
- legacy raw winner/ranking surfaces are retired from the primary dashboard
- performance validation is non-blocking when the workstation cannot reach a clean baseline
- System Idle Process is excluded from contamination reporting
- roadmap scope is frozen for 1.0; installer, ComfyUI, remote control, plugins, and broader runtime support are post-1.0 work

### Safety

- VektorDeck does not silently replace external llama.cpp listeners
- recovered runtime ownership is revalidated before use
- indexed asset paths are required for managed model/projector launch fields
- arbitrary extra arguments cannot override VektorDeck-owned launch controls
- contamination inspection is read-only
- diagnostics exclude `.env` contents and credentials

### Known release note

Controlled performance evidence may remain PENDING on systems that cannot currently reach the quiet-baseline thresholds. This is intentional and does not block daily-use readiness.
