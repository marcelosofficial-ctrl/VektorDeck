from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


BENCHMARK_PROMPT = (
    "Respond with exactly 80 to 120 words explaining why local AI inference "
    "benefits from sufficient VRAM, without using bullet points."
)


def _endpoint(profile: dict, path: str) -> str:
    host = str(profile.get("host", "127.0.0.1")).strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("benchmarking requires a loopback llama.cpp host")
    url_host = f"[{host}]" if ":" in host else host
    return f"http://{url_host}:{int(profile['port'])}{path}"


def _get_json(profile: dict, path: str, timeout_seconds: float) -> Any:
    with urllib.request.urlopen(_endpoint(profile, path), timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _slot_count_from_payload(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        direct = payload.get("total_slots")
        if isinstance(direct, int) and direct >= 0:
            return direct
        slots = payload.get("slots")
        if isinstance(slots, list):
            return len(slots)
    return None


def check_llama_health(profile: dict, timeout_seconds: float = 2.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        models_payload = _get_json(profile, "/v1/models", timeout_seconds)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return {
            "online": False,
            "latency_ms": None,
            "models": [],
            "total_slots": None,
            "slot_source": None,
            "model_path": None,
            "model_path_source": None,
            "modalities": None,
            "build_info": None,
            "build_info_source": None,
        }

    props: dict[str, Any] = {}
    try:
        payload = _get_json(profile, "/props", timeout_seconds)
        if isinstance(payload, dict):
            props = payload
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        pass

    total_slots = _slot_count_from_payload(props)
    slot_source = "props" if total_slots is not None else None
    if total_slots is None:
        try:
            total_slots = _slot_count_from_payload(_get_json(profile, "/slots", timeout_seconds))
            if total_slots is not None:
                slot_source = "slots"
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            pass

    models = models_payload.get("data", []) if isinstance(models_payload, dict) else []
    model_path = props.get("model_path")
    model_path_source = "props" if model_path else None
    if not model_path:
        model_path = profile.get("model_path")
        model_path_source = "profile" if model_path else None

    return {
        "online": True,
        "latency_ms": latency_ms,
        "models": models,
        "total_slots": total_slots,
        "slot_source": slot_source,
        "model_path": model_path,
        "model_path_source": model_path_source,
        "modalities": props.get("modalities"),
        "build_info": props.get("build_info"),
        "build_info_source": "props" if props.get("build_info") is not None else None,
    }


def run_benchmark(profile: dict, timeout_seconds: float = 120.0) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": "local-model",
            "messages": [{"role": "user", "content": BENCHMARK_PROMPT}],
            "temperature": 0.0,
            "max_tokens": 160,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _endpoint(profile, "/v1/chat/completions"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"llama.cpp benchmark HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"llama.cpp benchmark failed: {exc}") from exc

    elapsed = max(time.perf_counter() - started, 0.000001)
    usage = payload.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    timings = payload.get("timings") or {}
    server_tps = timings.get("predicted_per_second")
    measured_tps = None
    if isinstance(completion_tokens, int) and completion_tokens >= 0:
        measured_tps = round(completion_tokens / elapsed, 2)

    return {
        "elapsed_seconds": round(elapsed, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens_per_second": measured_tps,
        "server_tokens_per_second": round(float(server_tps), 2) if server_tps is not None else None,
        "response_preview": (
            (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        )[:240],
    }
