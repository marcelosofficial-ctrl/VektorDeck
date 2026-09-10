from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import ModelRepository
from .runtime import RuntimeManager, validate_profile_runtime


class ProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    model_path: str = Field(min_length=1)
    projector_path: str | None = None
    context_size: int = Field(default=65536, gt=0)
    gpu_layers: int = Field(default=99, ge=0)
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8080, ge=1, le=65535)
    extra_args: list[str] = Field(default_factory=list)


class ProfileDuplicate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _conflict_message(exc: sqlite3.IntegrityError) -> str:
    if "UNIQUE constraint failed" in str(exc):
        return "profile name already exists"
    return "profile update conflicts with database constraints"


def _indexed_kind(repository: ModelRepository, path: str) -> str | None:
    with repository.connect() as db:
        row = db.execute("SELECT kind FROM model_files WHERE path = ?", (path,)).fetchone()
    return str(row[0]) if row else None


def _validated_payload(repository: ModelRepository, payload: ProfilePayload) -> dict:
    data = payload.model_dump()
    try:
        validate_profile_runtime(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    model_kind = _indexed_kind(repository, data["model_path"])
    if model_kind != "model":
        raise HTTPException(
            status_code=400,
            detail="model_path must point to an indexed GGUF language model; scan the model library first",
        )

    projector_path = data.get("projector_path")
    if projector_path:
        projector_kind = _indexed_kind(repository, projector_path)
        if projector_kind != "projector":
            raise HTTPException(
                status_code=400,
                detail="projector_path must point to an indexed multimodal projector; scan the model library first",
            )
    return data


def build_profile_router(
    repository: ModelRepository,
    manager: RuntimeManager,
    llama_server_path: Path | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/profiles", tags=["profiles"])

    @router.get("")
    def profiles() -> list[dict]:
        return repository.list_profiles()

    @router.post("", status_code=201)
    def create_profile(payload: ProfilePayload) -> dict:
        try:
            return repository.create_profile(**_validated_payload(repository, payload))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=_conflict_message(exc)) from exc

    @router.put("/{profile_id}")
    def update_profile(profile_id: int, payload: ProfilePayload) -> dict:
        if manager.active_llama_profile_id() == profile_id:
            raise HTTPException(status_code=409, detail="stop this llama.cpp profile before editing it")
        try:
            profile = repository.update_profile(
                profile_id,
                **_validated_payload(repository, payload),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=_conflict_message(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        return profile

    @router.get("/{profile_id}/preview")
    def preview_profile(profile_id: int) -> dict:
        profile = repository.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        try:
            command = manager.preview_llama_command(llama_server_path, profile)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "profile_id": profile_id,
            "command": command,
            "display": subprocess_list2cmdline(command),
        }

    @router.post("/{profile_id}/default")
    def set_default(profile_id: int) -> dict:
        profile = repository.set_default_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        return profile

    @router.post("/{profile_id}/duplicate", status_code=201)
    def duplicate_profile(profile_id: int, payload: ProfileDuplicate) -> dict:
        try:
            profile = repository.duplicate_profile(profile_id, payload.name)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=_conflict_message(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail="launch profile not found")
        return profile

    @router.delete("/{profile_id}")
    def delete_profile(profile_id: int) -> dict:
        if manager.active_llama_profile_id() == profile_id:
            raise HTTPException(status_code=409, detail="stop this llama.cpp profile before deleting it")
        if not repository.delete_profile(profile_id):
            raise HTTPException(status_code=404, detail="launch profile not found")
        return {"deleted": True, "profile_id": profile_id}

    return router


def subprocess_list2cmdline(command: list[str]) -> str:
    """Use Windows-compatible quoting for a readable, copyable preview."""
    import subprocess

    return subprocess.list2cmdline(command)
