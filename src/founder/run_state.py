"""Shared deterministic job manifest helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from founder.paths import LakePaths
from founder.table_io import JsonRow, read_json, write_json

SECRET_KEY_PARTS = ("token", "secret", "password", "api_key", "authorization")


@dataclass(frozen=True)
class JobManifest:
    job_id: str
    job_type: str
    run_id: str
    status: str
    started_at: str
    finished_at: str
    input_paths: tuple[str, ...]
    output_paths: tuple[str, ...]
    row_counts: Mapping[str, int]
    concurrency: int | None = None
    resume_marker: str = ""
    error_summary: tuple[JsonRow, ...] = ()

    def as_dict(self) -> JsonRow:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_paths": list(self.input_paths),
            "output_paths": list(self.output_paths),
            "row_counts": dict(sorted(self.row_counts.items())),
            "concurrency": self.concurrency,
            "resume_marker": self.resume_marker,
            "error_summary": list(self.error_summary),
        }


def build_job_manifest(
    *,
    job_type: str,
    run_id: str,
    status: str,
    started_at: str = "",
    finished_at: str = "",
    input_paths: Sequence[Path | str] = (),
    output_paths: Sequence[Path | str] = (),
    row_counts: Mapping[str, int] | None = None,
    concurrency: int | None = None,
    resume_marker: str = "",
    error_summary: Sequence[Mapping[str, Any]] = (),
) -> JobManifest:
    if status not in {"planned", "running", "completed", "partial", "failed", "resumed"}:
        raise ValueError(f"unknown job status: {status}")
    return JobManifest(
        job_id=f"{job_type}:{run_id}",
        job_type=job_type,
        run_id=run_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        input_paths=tuple(sorted(str(path) for path in input_paths)),
        output_paths=tuple(sorted(str(path) for path in output_paths)),
        row_counts=dict(sorted((row_counts or {}).items())),
        concurrency=concurrency,
        resume_marker=resume_marker,
        error_summary=tuple(_redact_mapping(row) for row in error_summary),
    )


def write_job_manifest(paths: LakePaths, manifest: JobManifest) -> JsonRow:
    payload = manifest.as_dict()
    write_json(paths.job_manifest(manifest.job_type, manifest.run_id), payload)
    return payload


def read_job_manifest(paths: LakePaths, job_type: str, run_id: str) -> JsonRow:
    return read_json(paths.job_manifest(job_type, run_id))


def _redact_mapping(row: Mapping[str, Any]) -> JsonRow:
    redacted: JsonRow = {}
    for key, value in sorted(row.items()):
        normalized = str(key).casefold()
        if any(part in normalized for part in SECRET_KEY_PARTS):
            redacted[str(key)] = "<redacted>"
        elif isinstance(value, Mapping):
            redacted[str(key)] = _redact_mapping(cast(Mapping[str, Any], value))
        else:
            redacted[str(key)] = value
    return redacted
