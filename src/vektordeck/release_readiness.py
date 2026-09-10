from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark_protocol import BenchmarkProtocolRepository
from .database import ModelRepository
from .model_intelligence import ModelIntelligenceRepository


def _check(code: str, label: str, status: str, detail: str, blocking: bool) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "status": status,
        "detail": detail,
        "blocking": blocking,
    }


def assess_release_readiness(
    *,
    database_path: Path,
    llama_server_path: Path | None,
    a1111_launch_path: Path | None,
    hermes_cli_path: Path | None,
) -> dict[str, Any]:
    models = ModelRepository(database_path)
    intelligence = ModelIntelligenceRepository(database_path)
    protocols = BenchmarkProtocolRepository(database_path)
    intelligence.initialize()
    protocols.initialize()

    checks: list[dict[str, Any]] = []
    indexed = models.list_models()
    profiles = models.list_profiles()
    intel = intelligence.list_all()
    protocol_rows = protocols.list_recent(limit=200)

    language_models = [item for item in indexed if item.get("kind") == "model"]
    projectors = [item for item in indexed if item.get("kind") == "projector"]
    bad_intel = [item for item in intel if item.get("status") == "error"]
    inspected_models = [item for item in intel if item.get("status") == "ok"]

    if language_models:
        checks.append(_check("MODEL_INDEX", "Language model index", "PASS", f"{len(language_models)} language model(s) indexed", True))
    else:
        checks.append(_check("MODEL_INDEX", "Language model index", "FAIL", "No indexed GGUF language model is available", True))

    if inspected_models and not bad_intel:
        checks.append(_check("MODEL_INTELLIGENCE", "Model intelligence", "PASS", f"{len(inspected_models)} GGUF asset(s) inspected without errors", True))
    elif inspected_models:
        checks.append(_check("MODEL_INTELLIGENCE", "Model intelligence", "WARN", f"{len(bad_intel)} GGUF inspection error(s) remain", False))
    else:
        checks.append(_check("MODEL_INTELLIGENCE", "Model intelligence", "WARN", "GGUF metadata has not been inspected yet", False))

    if profiles:
        default_count = sum(1 for profile in profiles if profile.get("is_default"))
        if default_count == 1:
            checks.append(_check("PROFILES", "Launch profiles", "PASS", f"{len(profiles)} saved profile(s), exactly one default", True))
        else:
            checks.append(_check("PROFILES", "Launch profiles", "FAIL", f"Expected exactly one default profile, found {default_count}", True))
    else:
        checks.append(_check("PROFILES", "Launch profiles", "FAIL", "No saved launch profile is available", True))

    runtime_paths = [
        ("LLAMA", "llama.cpp", llama_server_path, True),
        ("A1111", "Image Studio", a1111_launch_path, False),
        ("HERMES", "Hermes", hermes_cli_path, False),
    ]
    for code, label, path, blocking in runtime_paths:
        if path and path.exists():
            checks.append(_check(code, label, "PASS", str(path), blocking))
        else:
            status = "FAIL" if blocking else "WARN"
            checks.append(_check(code, label, status, "Configured executable/launcher was not found", blocking))

    if projectors:
        checks.append(_check("PROJECTOR", "Vision projector", "PASS", f"{len(projectors)} projector(s) indexed", False))
    else:
        checks.append(_check("PROJECTOR", "Vision projector", "WARN", "No multimodal projector is indexed", False))

    clean_v2 = [
        row for row in protocol_rows
        if int(row.get("protocol_version") or 0) >= 2 and bool(row.get("baseline_ready"))
    ]
    if len(clean_v2) >= 2:
        checks.append(_check("EVIDENCE", "Controlled benchmark evidence", "PASS", f"{len(clean_v2)} protocol-v2 quiet-baseline run(s) recorded", False))
    else:
        checks.append(_check("EVIDENCE", "Controlled benchmark evidence", "PENDING", "Performance validation is still pending; this does not block daily-use readiness", False))

    blocking_failures = [item for item in checks if item["blocking"] and item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] in {"WARN", "PENDING"}]
    status = "BLOCKED" if blocking_failures else "READY_WITH_NOTES" if warnings else "READY"

    return {
        "status": status,
        "checks": checks,
        "blocking_failures": len(blocking_failures),
        "notes": len(warnings),
        "summary": (
            "Core local-AI workflow is ready for daily use."
            if not blocking_failures
            else "One or more core release requirements are not satisfied."
        ),
    }
