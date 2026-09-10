from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .model_compatibility import filename_quantization, projector_pairing_hints
from .quality import classify_benchmark

GIB = 1024 ** 3
TRUSTWORTHY = {"HEALTHY", "TIGHT"}
MIN_TRUSTWORTHY_RUNS = 2


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _same_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _norm(left) == _norm(right)


def _protocol_v2_eligible(run: dict[str, Any]) -> bool:
    return int(run.get("protocol_version") or 0) >= 2 and run.get("baseline_ready") is True


def _parallel_one(args: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(args):
        arg = str(args[index])
        if arg in {"--parallel", "-np"}:
            index += 2
            continue
        if arg.startswith("--parallel="):
            index += 1
            continue
        result.append(arg)
        index += 1
    result.extend(["--parallel", "1"])
    return result


def _with_image_floor(args: list[str], supported: bool) -> list[str]:
    if not supported:
        return args
    for index, arg in enumerate(args):
        if arg == "--image-min-tokens" and index + 1 < len(args):
            return args
        if arg.startswith("--image-min-tokens="):
            return args
    return [*args, "--image-min-tokens", "1024"]


def _unique_name(base: str, existing_names: set[str]) -> str:
    clean = re.sub(r"\s+", " ", base).strip()[:80]
    if clean not in existing_names:
        return clean
    for index in range(2, 100):
        suffix = f" {index}"
        candidate = clean[: 80 - len(suffix)] + suffix
        if candidate not in existing_names:
            return candidate
    return clean[:72] + " copy"


def _heuristic_context(
    *,
    advertised_context: int | None,
    total_ram_bytes: int | None,
    total_vram_bytes: int | None,
    model_size_bytes: int,
    multimodal: bool,
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    ram_gib = total_ram_bytes / GIB if total_ram_bytes else None
    vram_gib = total_vram_bytes / GIB if total_vram_bytes else None
    model_gib = model_size_bytes / GIB

    if ram_gib is not None and ram_gib >= 63 and (vram_gib is None or vram_gib >= 20):
        context = 32768
        reasons.append("64 GB-class system memory supports the 32K starting tier")
    elif ram_gib is not None and ram_gib >= 31 and (vram_gib is None or vram_gib >= 12):
        context = 16384
        reasons.append("32 GB-class RAM and 12+ GiB VRAM map to the 16K starting tier")
    elif ram_gib is not None and ram_gib >= 24:
        context = 8192
        reasons.append("available system memory maps to the 8K starting tier")
    else:
        context = 4096
        reasons.append("conservative 4K context selected for limited or unknown memory capacity")

    if total_vram_bytes:
        vram_ratio = model_size_bytes / total_vram_bytes
        if vram_ratio >= 0.85:
            reduced = max(4096, context // 2)
            if reduced < context:
                context = reduced
                reasons.append(
                    f"model file is {model_gib:.1f} GiB, at least 85% of total VRAM capacity, so context was reduced one tier"
                )
        elif vram_ratio >= 0.65 and context > 8192:
            reduced = max(8192, context // 2)
            if reduced < context:
                context = reduced
                reasons.append(
                    f"model file is {model_gib:.1f} GiB, at least 65% of total VRAM capacity, so context was reduced one tier"
                )

    if total_ram_bytes and total_ram_bytes < model_size_bytes * 2.5:
        reduced = min(context, 8192)
        if reduced < context:
            context = reduced
            reasons.append("system RAM is below 2.5× model file size, so context was capped at 8K")

    if multimodal and context > 16384:
        context = 16384
        reasons.append("multimodal profile starts at no more than 16K until benchmark evidence proves more headroom")

    if isinstance(advertised_context, int) and advertised_context > 0 and context > advertised_context:
        context = max(1024, advertised_context)
        reasons.append(f"context capped to GGUF-advertised limit of {advertised_context:,}")

    return int(context), reasons


def _trustworthy_profile_summary(
    profiles: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
    model_path: str,
) -> dict[str, Any] | None:
    current = {
        int(profile["id"]): profile
        for profile in profiles
        if _same_path(profile.get("model_path"), model_path)
    }
    grouped: dict[int, list[float]] = {}
    for run in benchmarks:
        if not _same_path(run.get("model_path"), model_path):
            continue
        if not _protocol_v2_eligible(run):
            continue
        quality = classify_benchmark(run)["quality"]
        if quality not in TRUSTWORTHY:
            continue
        profile_id = int(run.get("profile_id") or 0)
        if profile_id not in current:
            continue
        speed = run.get("server_tokens_per_second")
        if speed is None:
            speed = run.get("tokens_per_second")
        if not isinstance(speed, (int, float)) or speed <= 0:
            continue
        grouped.setdefault(profile_id, []).append(float(speed))

    ranked: list[tuple[float, int, list[float]]] = []
    for profile_id, values in grouped.items():
        if len(values) < MIN_TRUSTWORTHY_RUNS:
            continue
        ranked.append((sum(values) / len(values), profile_id, values))
    if not ranked:
        return None

    ranked.sort(reverse=True)
    average, profile_id, values = ranked[0]
    return {
        "profile": current[profile_id],
        "runs": len(values),
        "average_tokens_per_second": round(average, 2),
        "best_tokens_per_second": round(max(values), 2),
    }


def build_recommendation(
    *,
    model_path: str,
    indexed_models: list[dict[str, Any]],
    intelligence: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
    total_ram_bytes: int | None,
    total_vram_bytes: int | None,
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    capabilities = capabilities or {}
    indexed_by_path = {_norm(str(item["path"])): item for item in indexed_models}
    metadata_by_path = {_norm(str(item["path"])): item for item in intelligence}
    model = indexed_by_path.get(_norm(model_path))

    if model is None or model.get("kind") != "model" or not Path(model_path).is_file():
        return {
            "status": "BLOCKED",
            "source": "NONE",
            "model_path": model_path,
            "reasons": ["model must be indexed as a language model and present on disk"],
            "profile": None,
        }

    metadata = metadata_by_path.get(_norm(model_path))
    pairing = next(
        (
            item
            for item in projector_pairing_hints(indexed_models)
            if _same_path(item["model_path"], model_path)
        ),
        None,
    )
    recommended_projector = pairing.get("recommended_projector") if pairing else None

    evidence = _trustworthy_profile_summary(profiles, benchmarks, model_path)
    existing_names = {str(profile["name"]) for profile in profiles}
    display_name = (
        metadata.get("display_name")
        if metadata and isinstance(metadata.get("display_name"), str)
        else Path(model_path).stem
    )

    if evidence is not None:
        profile = evidence["profile"]
        reasons = [
            f"uses {evidence['runs']} protocol-v2 HEALTHY/TIGHT benchmark run(s) from an existing profile",
            f"average generation speed {evidence['average_tokens_per_second']:.2f} tok/s; best {evidence['best_tokens_per_second']:.2f} tok/s",
            "promotion evidence required a recorded quiet baseline; pressured, contaminated, and legacy runs were excluded",
        ]
        return {
            "status": "EVIDENCE_BACKED",
            "source": "TRUSTWORTHY_BENCHMARK",
            "model_path": model_path,
            "architecture": metadata.get("architecture") if metadata else None,
            "quantization_hint": filename_quantization(model_path),
            "machine": {
                "ram_total_bytes": total_ram_bytes,
                "vram_total_bytes": total_vram_bytes,
            },
            "pairing": pairing,
            "evidence": evidence,
            "reasons": reasons,
            "profile": {
                "name": _unique_name(f"{profile['name']} recommended", existing_names),
                "model_path": profile["model_path"],
                "projector_path": profile.get("projector_path"),
                "context_size": int(profile["context_size"]),
                "gpu_layers": int(profile["gpu_layers"]),
                "host": str(profile["host"]),
                "port": int(profile["port"]),
                "extra_args": list(profile.get("extra_args") or []),
            },
        }

    default_match = next(
        (
            profile
            for profile in profiles
            if profile.get("is_default") and _same_path(profile.get("model_path"), model_path)
        ),
        None,
    )
    any_match = next(
        (profile for profile in profiles if _same_path(profile.get("model_path"), model_path)),
        None,
    )
    base = default_match or any_match
    advertised_context = (
        metadata.get("context_length")
        if metadata and metadata.get("status") == "ok"
        else None
    )
    projector_path = (
        recommended_projector.get("path")
        if recommended_projector
        else (base.get("projector_path") if base else None)
    )
    multimodal = bool(projector_path)
    context, context_reasons = _heuristic_context(
        advertised_context=advertised_context if isinstance(advertised_context, int) else None,
        total_ram_bytes=total_ram_bytes,
        total_vram_bytes=total_vram_bytes,
        model_size_bytes=int(model.get("size_bytes") or 0),
        multimodal=multimodal,
    )

    extra_args = _parallel_one(list(base.get("extra_args") or []) if base else [])
    if multimodal:
        extra_args = _with_image_floor(extra_args, bool(capabilities.get("image_min_tokens")))

    pressured_count = 0
    unverified_count = 0
    protocol_v2_clean_count = 0
    legacy_trustworthy_count = 0
    for run in benchmarks:
        if not _same_path(run.get("model_path"), model_path):
            continue
        quality = classify_benchmark(run)["quality"]
        if quality == "PRESSURED":
            pressured_count += 1
        elif quality == "UNVERIFIED":
            unverified_count += 1
        elif quality in TRUSTWORTHY:
            if _protocol_v2_eligible(run):
                protocol_v2_clean_count += 1
            else:
                legacy_trustworthy_count += 1

    reasons = [
        *context_reasons,
        "single-user --parallel 1 is used as the conservative starting point",
    ]
    if multimodal and capabilities.get("image_min_tokens"):
        reasons.append(
            "vision profile includes llama.cpp's advertised --image-min-tokens 1024 floor"
        )
    elif multimodal:
        reasons.append(
            "installed llama-server --help did not advertise --image-min-tokens, so VektorDeck did not inject that flag"
        )
    if recommended_projector:
        reasons.append("projector is suggested from local folder/name pairing evidence")
    if pressured_count:
        reasons.append(
            f"{pressured_count} existing pressured benchmark run(s) were excluded from recommendation evidence"
        )
    if unverified_count:
        reasons.append(f"{unverified_count} legacy/unverified benchmark run(s) were excluded")
    if legacy_trustworthy_count:
        reasons.append(
            f"{legacy_trustworthy_count} HEALTHY/TIGHT run(s) lack protocol-v2 quiet-baseline evidence and cannot promote a profile"
        )
    if 0 < protocol_v2_clean_count < MIN_TRUSTWORTHY_RUNS:
        reasons.append(
            f"only {protocol_v2_clean_count} protocol-v2 trustworthy run(s) exist; {MIN_TRUSTWORTHY_RUNS} are required before promotion"
        )
    reasons.append(
        "this is a hardware heuristic and must earn two protocol-v2 HEALTHY/TIGHT runs before becoming evidence-backed"
    )

    return {
        "status": "EXPERIMENTAL",
        "source": "HARDWARE_HEURISTIC",
        "model_path": model_path,
        "architecture": metadata.get("architecture") if metadata else None,
        "quantization_hint": filename_quantization(model_path),
        "machine": {
            "ram_total_bytes": total_ram_bytes,
            "vram_total_bytes": total_vram_bytes,
        },
        "pairing": pairing,
        "evidence": None,
        "reasons": reasons,
        "profile": {
            "name": _unique_name(f"{display_name} suggested {context // 1024}K", existing_names),
            "model_path": model_path,
            "projector_path": projector_path,
            "context_size": context,
            "gpu_layers": int(base.get("gpu_layers") if base else 99),
            "host": str(base.get("host") if base else "127.0.0.1"),
            "port": int(base.get("port") if base else 8080),
            "extra_args": extra_args,
        },
    }
