<div align="center">

<img src="https://raw.githubusercontent.com/marcelosofficial-ctrl/portfolio/main/public/brand/vektordeck.webp" alt="VektorDeck icon" width="112" />

# VektorDeck

**Local-first control deck for serious local AI workstations.**

[![CI](https://github.com/marcelosofficial-ctrl/VektorDeck/actions/workflows/ci.yml/badge.svg)](https://github.com/marcelosofficial-ctrl/VektorDeck/actions/workflows/ci.yml)
![Release](https://img.shields.io/badge/release-1.0.0-d6ff57?labelColor=111416)
![Local first](https://img.shields.io/badge/local--first-no%20cloud%20account-d6ff57?labelColor=111416)

[Portfolio case study](https://marcelosofficial-ctrl.github.io/portfolio/projects/vektordeck/) · [Release notes](docs/release-notes-1.0.0.md) · [Architecture](#architecture)

</div>

VektorDeck is a local-first workstation manager for inspecting, launching, benchmarking, and comparing local AI runtimes on consumer hardware.

It was built around a practical problem: local AI workflows become difficult to trust once model files, launch flags, multimodal projectors, runtime processes, hardware limits, and benchmark results are spread across different folders and terminals.

VektorDeck brings those concerns into one local control deck without requiring a cloud account.

## What it does

### Model intelligence

- indexes local `.gguf` language models and multimodal projectors
- discovers Stable Diffusion `.safetensors` / `.ckpt` checkpoints from AUTOMATIC1111-style installs
- preserves separate physical files and duplicate copies
- reads bounded GGUF metadata without loading a model for inference
- exposes architecture, advertised context, tensor count, parameter/size hints, quantization metadata, and selected GGUF keys
- caches unchanged metadata in SQLite
- suggests projector pairings from local folder/name evidence
- classifies saved profiles as `READY`, `WARN`, or `BLOCKED`

### Safe runtime control

VektorDeck manages:

- llama.cpp
- AUTOMATIC1111 / AMD image generation
- Hermes Desktop

Runtime safety includes:

- loopback-only llama.cpp profiles
- port preflight before launch
- exact model/projector path validation against indexed assets
- protection against profile arguments overriding VektorDeck-owned launch settings
- external-process detection
- refusal to replace or stop processes VektorDeck does not own
- persistent llama.cpp ownership leases
- validated runtime recovery after backend restart

### Smart Launch

Smart Launch produces explainable local recommendations instead of an opaque score.

A recommendation is either:

- `EXPERIMENTAL`, derived conservatively from model size, GGUF context metadata, RAM, VRAM, projector pairing, saved profile settings, and local llama.cpp capabilities
- `EVIDENCE-BACKED`, only after repeated controlled benchmark evidence qualifies

Experimental single-user profiles use `--parallel 1`. Vision flags such as `--image-min-tokens 1024` are only injected when the installed llama.cpp build actually advertises them.

Smart Launch never silently launches, replaces, promotes, or makes a profile default.

## Benchmark Protocol v2

VektorDeck treats benchmark results as evidence, not decoration.

A controlled Protocol-v2 run can preserve both the workstation baseline before inference and hardware pressure during inference:

- protocol version and run source
- quiet-baseline result
- baseline CPU/RAM/GPU average and peak values
- baseline refusal reasons
- bounded read-only top-process snapshot
- inference CPU/RAM/GPU/VRAM evidence
- tokens/sec and runtime timing

Runs are classified as `HEALTHY`, `TIGHT`, `PRESSURED`, or `UNVERIFIED` using explicit memory-headroom rules.

Smart Launch promotion requires at least two Protocol-v2 runs for the same saved profile that began from a recorded quiet baseline and finished as HEALTHY/TIGHT. Legacy, pressured, unverified, or contaminated runs remain visible but cannot become trusted winners.

If the workstation cannot currently reach a clean baseline, performance validation remains `PENDING`. VektorDeck does not fabricate clean evidence to finish a benchmark.

## Contamination inspector

When a benchmark preflight is busy, VektorDeck can show a short read-only list of likely contaminating processes using:

- PID
- process name
- process role (`user`, `system`, or `vektordeck_backend`)
- normalized whole-machine CPU percentage
- working-set RAM

Windows' `System Idle Process` is excluded because it represents unused CPU capacity rather than work.

The inspector never kills, suspends, reprioritizes, or modifies processes.

## Release readiness

The **READINESS** drawer evaluates whether the local installation is ready for everyday use.

Core checks include:

- at least one indexed GGUF language model
- saved launch profiles with exactly one default
- configured llama.cpp executable present
- Model Intelligence state
- optional Image Studio / Hermes availability
- vision projector availability
- Protocol-v2 benchmark evidence state

Performance validation is intentionally non-blocking when the machine cannot reach a quiet baseline. The readiness surface distinguishes core blockers from notes and pending evidence, and records when the check was last refreshed.

## Dashboard

The React + TypeScript dashboard includes:

- live CPU/RAM/GPU/VRAM telemetry and rolling history
- runtime launch/stop controls
- combined Qwen + Hermes workspace control
- Model Inspector
- Smart Launch
- Profile Manager
- Protocol-aware Trends
- Memory Optimizer
- runtime observability/logs
- Release Readiness

Legacy benchmark ranking surfaces are retired from the main UI. Historical benchmark rows remain preserved in SQLite and visible through evidence-focused views.

## Windows workflow

Normal use does not require remembering development commands.

Double-click:

```text
Start VektorDeck.cmd
Stop VektorDeck.cmd
Update VektorDeck.cmd
Repair VektorDeck.cmd
Collect VektorDeck Diagnostics.cmd
```

`Update VektorDeck.cmd`:

1. pulls current code first
2. automatically re-execs itself if the updater changed during the pull
3. stops VektorDeck-managed runtimes and app process trees
4. verifies local ports are released
5. refreshes Python/frontend dependencies only when manifests changed
6. runs the Python regression suite
7. runs a production TypeScript/Vite build
8. relaunches only when validation passes
9. performs a read-only live smoke check against the relaunched backend/frontend

The live smoke check verifies backend health, SQLite, model/profile/runtime APIs, telemetry, release readiness, and the frontend HTTP response without launching a model or starting a benchmark.

A full update transcript is saved to `VektorDeck-Update-Last.txt` on the Windows Desktop.

`Collect VektorDeck Diagnostics.cmd` creates a shareable local report containing repository/version state, ports, runtime ownership, machine telemetry, top-process contamination context, recent benchmark protocol metadata, and the llama.cpp log tail. `.env` contents and credentials are intentionally excluded.

## Validation layers

VektorDeck 1.0 uses three separate validation gates:

1. GitHub Actions CI: dependency install, critical Ruff checks, pytest, and production frontend build
2. local update validation: the same Python regression suite plus production frontend build on the target Windows machine
3. live post-relaunch smoke check: read-only verification of the running installation

Performance evidence is intentionally separate from release correctness. A busy workstation can leave controlled performance evidence pending without making the application itself unready.

## Architecture

```text
React / TypeScript dashboard
            |
            | loopback HTTP
            v
       FastAPI backend
            |
   +--------+--------------------+-----------------------+
   |                             |                       |
Asset scanning             Model intelligence       Runtime manager
   |                        Smart Launch                |
   |                             |                llama / A1111 / Hermes
   v                             v                       |
Local model roots             SQLite              health / logs / props
                      assets / profiles / evidence
                      benchmark protocol provenance
```

## Repository layout

```text
src/vektordeck/      Python backend
web/                 React + TypeScript dashboard
tests/               regression tests
docs/                engineering notes
scripts/             Windows workflow
.github/workflows/   CI
```

Key engineering notes:

- [`docs/model-intelligence.md`](docs/model-intelligence.md)
- [`docs/smart-launch.md`](docs/smart-launch.md)
- [`docs/benchmark-protocol-v2.md`](docs/benchmark-protocol-v2.md)
- [`docs/roadmap.md`](docs/roadmap.md)
- [`docs/release-notes-1.0.0.md`](docs/release-notes-1.0.0.md)

## Status

**VektorDeck 1.0.0** is the first completed product release for the current Windows local-workstation scope.

Packaged installers, ComfyUI integration, remote/mobile control, plugin architecture, and broader runtime support are intentionally post-1.0 extensions rather than unfinished release requirements.
