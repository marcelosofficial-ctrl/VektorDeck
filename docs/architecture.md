# Architecture

VektorDeck is deliberately local-first. The browser UI is a control surface for a loopback-only FastAPI process. That backend owns filesystem access, SQLite persistence and runtime process management.

## Boundaries

- **UI:** presentation and user intent only. It never scans drives directly.
- **API:** validates commands and exposes local system state.
- **Services:** model discovery, runtime inspection and later process lifecycle/telemetry.
- **SQLite:** durable local state, benchmark history and launch presets.
- **llama.cpp:** remains an external runtime. VektorDeck supervises it rather than embedding or forking it.

This keeps model/runtime concerns replaceable and makes the core easy to test without a GPU.

## 0.1 invariants

1. Re-scanning the same files must not duplicate them.
2. Missing scan roots are skipped rather than crashing the whole scan.
3. Runtime absence is a valid state, not an exception.
4. The backend binds to `127.0.0.1` by default.
5. SQLite integrity must remain `ok` after normal operations.
