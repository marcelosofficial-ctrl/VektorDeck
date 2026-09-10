# Benchmark Protocol v2

VektorDeck 0.5 introduces a second layer of benchmark evidence: the machine baseline that existed before inference started.

## Why protocol v2 exists

Inference-time telemetry alone cannot tell whether a benchmark began on a clean workstation or whether unrelated background work was already consuming CPU, RAM or GPU resources.

Protocol v2 therefore records both:

1. pre-launch workstation baseline
2. inference-time hardware evidence

A benchmark can only be used for Smart Launch promotion when both layers are trustworthy.

## Protocol record

Protocol-v2 data is stored in a companion SQLite table keyed by `benchmark_id`. Existing benchmark rows are not rewritten.

Each record stores:

- protocol version
- run source (`smart_launch`, `optimizer`, or `manual`)
- whether the preflight baseline was ready
- baseline sample count
- baseline CPU average / peak
- baseline RAM average / peak
- baseline GPU average / peak
- baseline refusal reasons
- a bounded read-only snapshot of top processes

This keeps historical benchmark evidence intact while allowing newer controlled runs to carry richer provenance.

## Quiet-baseline rules

The existing explicit preflight thresholds remain authoritative:

- background CPU average must stay below 55%
- background CPU peak must stay below 75%
- baseline RAM average must stay below 70%
- background GPU average must stay below 55%

Smart Launch and Memory Optimizer refuse to start controlled runs when those conditions are not met.

## Process contamination inspector

When the workstation is busy, VektorDeck can collect a short read-only process snapshot using `psutil`.

The inspector records:

- PID
- process name
- normalized whole-machine CPU percentage
- working-set RAM in bytes / MB

The process inspector does not terminate, suspend, reprioritize, or mutate processes.

Its purpose is diagnostic only: explain why a benchmark could not start without forcing the user to hunt through Task Manager or PowerShell.

## Promotion rules

Smart Launch promotion requires all of the following for the same saved profile:

- at least two benchmark runs
- protocol version >= 2
- recorded quiet baseline (`baseline_ready = true`)
- inference quality classified as HEALTHY or TIGHT
- positive generation speed

The following cannot promote a profile:

- legacy runs without protocol metadata
- runs that began from a busy baseline
- PRESSURED runs
- UNVERIFIED runs
- one-off clean runs without a second matching controlled result

## Trends

The Trends drawer keeps all historical runs visible but separates protocol-v2 evidence from legacy history.

The trustworthy ranking uses only:

- protocol-v2
- quiet-baseline
- HEALTHY/TIGHT
- minimum two runs per profile

This prevents an older or contaminated benchmark from becoming a recommendation simply because it happened to report a higher tokens-per-second number.

## Update workflow

0.5 also makes the updater dependency-aware.

The updater hashes `pyproject.toml` and `web/package.json` and only refreshes Python/frontend dependencies when those manifests change. This allows new dependencies such as `psutil` to install automatically without reinstalling dependency trees on every update.
