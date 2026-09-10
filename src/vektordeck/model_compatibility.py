from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9]+")
# Match common GGUF quantization names as one complete token. The repeated
# underscore groups are important for variants such as Q4_K_M, Q5_K_S,
# IQ3_XS and Q8_0 rather than truncating them after the first suffix.
QUANT_RE = re.compile(
    r"(?:^|[._-])((?:I?Q\d(?:_[A-Z0-9]+)*)|F16|F32|BF16)(?=[._-]|$)",
    re.IGNORECASE,
)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def filename_quantization(path: str) -> str | None:
    match = QUANT_RE.search(Path(path).name)
    return match.group(1).upper() if match else None


def _name_tokens(path: str) -> set[str]:
    name = Path(path).stem.lower()
    ignored = {
        "gguf", "mmproj", "projector", "vision", "model", "bf16", "f16", "f32",
        "q2", "q3", "q4", "q5", "q6", "q8", "iq1", "iq2", "iq3", "iq4",
    }
    return {token for token in TOKEN_RE.findall(name) if len(token) >= 3 and token not in ignored}


def projector_pairing_hints(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    language = [item for item in models if item.get("kind") == "model"]
    projectors = [item for item in models if item.get("kind") == "projector"]
    hints: list[dict[str, Any]] = []

    for model in language:
        model_path = str(model["path"])
        model_parent = _norm(str(Path(model_path).parent))
        model_tokens = _name_tokens(model_path)
        ranked: list[dict[str, Any]] = []
        for projector in projectors:
            projector_path = str(projector["path"])
            reasons: list[str] = []
            score = 0
            if _norm(str(Path(projector_path).parent)) == model_parent:
                score += 100
                reasons.append("same folder")
            overlap = sorted(model_tokens & _name_tokens(projector_path))
            if overlap:
                score += min(len(overlap) * 10, 40)
                reasons.append("shared name tokens: " + ", ".join(overlap[:4]))
            if "mmproj" in Path(projector_path).name.lower():
                score += 15
                reasons.append("mmproj naming convention")
            ranked.append(
                {
                    "path": projector_path,
                    "name": projector.get("name") or Path(projector_path).name,
                    "score": score,
                    "reasons": reasons or ["no strong local pairing signal"],
                }
            )
        ranked.sort(key=lambda item: (-int(item["score"]), str(item["name"]).lower()))
        hints.append(
            {
                "model_path": model_path,
                "model_name": model.get("name") or Path(model_path).name,
                "recommended_projector": ranked[0] if ranked and ranked[0]["score"] > 0 else None,
                "candidates": ranked,
            }
        )
    return hints


def profile_readiness(
    profile: dict[str, Any],
    indexed_models: list[dict[str, Any]],
    intelligence: list[dict[str, Any]],
) -> dict[str, Any]:
    indexed = {_norm(str(item["path"])): item for item in indexed_models}
    metadata = {_norm(str(item["path"])): item for item in intelligence}
    reasons: list[dict[str, str]] = []

    model_path = str(profile.get("model_path") or "")
    projector_path = str(profile.get("projector_path") or "") if profile.get("projector_path") else None
    model_item = indexed.get(_norm(model_path)) if model_path else None
    model_meta = metadata.get(_norm(model_path)) if model_path else None

    blocked = False
    warned = False

    if not model_item or model_item.get("kind") != "model":
        blocked = True
        reasons.append({"level": "BLOCKED", "message": "model path is not an indexed language model"})
    elif not Path(model_path).is_file():
        blocked = True
        reasons.append({"level": "BLOCKED", "message": "model file is missing from disk"})
    else:
        reasons.append({"level": "OK", "message": "language model is indexed and present"})

    if projector_path:
        projector_item = indexed.get(_norm(projector_path))
        if not projector_item or projector_item.get("kind") != "projector":
            blocked = True
            reasons.append({"level": "BLOCKED", "message": "projector path is not an indexed projector"})
        elif not Path(projector_path).is_file():
            blocked = True
            reasons.append({"level": "BLOCKED", "message": "projector file is missing from disk"})
        else:
            reasons.append({"level": "OK", "message": "multimodal projector is indexed and present"})

    if model_meta is None:
        warned = True
        reasons.append({"level": "WARN", "message": "GGUF metadata has not been inspected yet"})
    elif model_meta.get("status") == "error":
        warned = True
        reasons.append({"level": "WARN", "message": "GGUF metadata inspection reported an error"})
    else:
        advertised_context = model_meta.get("context_length")
        requested_context = int(profile.get("context_size") or 0)
        if isinstance(advertised_context, int) and advertised_context > 0:
            if requested_context > advertised_context:
                warned = True
                reasons.append(
                    {
                        "level": "WARN",
                        "message": f"profile requests {requested_context:,} context but GGUF advertises {advertised_context:,}",
                    }
                )
            else:
                reasons.append(
                    {
                        "level": "OK",
                        "message": f"profile context {requested_context:,} is within GGUF metadata limit {advertised_context:,}",
                    }
                )

    if str(profile.get("host", "")).lower() not in {"127.0.0.1", "localhost", "::1"}:
        blocked = True
        reasons.append({"level": "BLOCKED", "message": "runtime host is not loopback-only"})

    status = "BLOCKED" if blocked else "WARN" if warned else "READY"
    return {
        "profile_id": int(profile["id"]),
        "profile_name": str(profile["name"]),
        "status": status,
        "model_path": model_path,
        "projector_path": projector_path,
        "quantization_hint": filename_quantization(model_path),
        "architecture": model_meta.get("architecture") if model_meta else None,
        "advertised_context": model_meta.get("context_length") if model_meta else None,
        "requested_context": int(profile.get("context_size") or 0),
        "reasons": reasons,
    }
