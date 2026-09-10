# VektorDeck 1.0.0

VektorDeck 1.0 is the first completed release of the Windows local-AI workstation manager.

## Why this release exists

Local AI setups often grow into a collection of folders, command lines, model files, launch flags, runtime processes, and benchmark notes that are difficult to reason about together. VektorDeck turns that setup into one local control surface and, more importantly, keeps recommendations tied to visible evidence instead of opaque scores.

## Release highlights

### Model Intelligence

VektorDeck can inspect local GGUF metadata without loading the model for inference. The inspector exposes architecture, advertised context, tensor count, parameter/size hints, quantization metadata, and bounded selected metadata while caching unchanged files in SQLite.

### Runtime safety

Managed llama.cpp launches are loopback-only, preflight their ports, validate indexed model/projector paths, protect VektorDeck-owned launch flags, and refuse to replace or stop unrelated external listeners.

Persistent runtime leases allow a surviving llama.cpp process to be recovered after a backend restart only when PID, executable path, port, model, and live llama-compatible API still agree.

### Smart Launch

Smart Launch distinguishes between:

- `EXPERIMENTAL`: hardware/model heuristic that still needs controlled evidence
- `EVIDENCE-BACKED`: repeated qualifying benchmark evidence

Recommendations are explainable, never silently launched, and never silently made default.

### Benchmark Protocol v2

Controlled benchmark evidence can preserve the quiet-machine baseline before inference, likely contaminating processes, and inference-time CPU/RAM/GPU/VRAM pressure.

Legacy, pressured, unverified, or contaminated runs remain visible as history but cannot promote a profile.

### Release Readiness

The Readiness drawer checks whether the installation is usable for the current 1.0 scope. Core runtime/model/profile failures block readiness. Optional integrations and pending controlled performance evidence are shown as notes rather than being hidden.

A machine that cannot currently reach the benchmark quiet-baseline thresholds can still be release-ready for daily use.

### Windows workflow

The project includes double-click Start, Stop, Update, Repair, and Diagnostics workflows.

The updater now:

1. pulls current code
2. re-execs itself if its own script changed during that pull
3. safely stops managed process trees
4. verifies ports are free
5. refreshes dependencies only when manifests change
6. runs pytest
7. runs the production frontend build
8. relaunches VektorDeck
9. performs a read-only live smoke check

## Validation model

A successful 1.0 update is expected to pass three independent layers:

- GitHub Actions CI
- local Windows regression/build validation
- post-relaunch live smoke validation

Performance benchmarking is kept separate from release correctness so VektorDeck never has to manufacture a clean benchmark to claim the application works.

## 1.0 scope

Included:

- Windows local workstation management
- llama.cpp
- AUTOMATIC1111-style Image Studio launch control
- Hermes integration
- GGUF model intelligence
- profiles
- telemetry
- evidence-aware benchmarking
- Smart Launch
- Memory Optimizer
- diagnostics
- readiness checks

Explicitly post-1.0:

- packaged installer
- ComfyUI adapter
- remote/mobile control
- plugin architecture
- broader runtime/vendor support

Those are extensions, not missing pieces of the 1.0 product.
