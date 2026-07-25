"""Immutable report lineage and export manifest models."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType

_GIT_COMMIT = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _nonempty_text(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"{field_name} must contain non-empty entries")
    return normalized


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    """Complete, immutable lineage required to reproduce and interpret an export."""

    engine_version: str
    git_commit: str
    data_hashes: Mapping[str, str]
    policy_cutoff: date
    actual_session_cutoff: date
    generated_at: datetime
    timezone: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        engine_version = self.engine_version.strip()
        git_commit = self.git_commit.strip().lower()
        timezone = self.timezone.strip()
        if not engine_version:
            raise ValueError("engine version is required")
        if not _GIT_COMMIT.fullmatch(git_commit):
            raise ValueError("git commit must be a hexadecimal commit identifier")
        if not timezone:
            raise ValueError("timezone is required")
        if self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.actual_session_cutoff > self.policy_cutoff:
            raise ValueError("actual session cutoff cannot exceed policy cutoff")

        hashes = dict(sorted(self.data_hashes.items()))
        if not hashes:
            raise ValueError("at least one data hash is required")
        for symbol, digest in hashes.items():
            if not symbol.strip():
                raise ValueError("data hash symbols cannot be empty")
            if not _SHA256.fullmatch(digest):
                raise ValueError(f"data hash for {symbol} must be SHA-256")

        object.__setattr__(self, "engine_version", engine_version)
        object.__setattr__(self, "git_commit", git_commit)
        object.__setattr__(self, "timezone", timezone)
        object.__setattr__(
            self,
            "data_hashes",
            MappingProxyType({symbol: digest.lower() for symbol, digest in hashes.items()}),
        )
        object.__setattr__(
            self,
            "assumptions",
            _nonempty_text(self.assumptions, "assumptions"),
        )
        object.__setattr__(
            self,
            "limitations",
            _nonempty_text(self.limitations, "limitations"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "actual_session_cutoff": self.actual_session_cutoff.isoformat(),
            "assumptions": list(self.assumptions),
            "data_hashes": dict(self.data_hashes),
            "engine_version": self.engine_version,
            "generated_at": self.generated_at.isoformat(),
            "git_commit": self.git_commit,
            "limitations": list(self.limitations),
            "policy_cutoff": self.policy_cutoff.isoformat(),
            "timezone": self.timezone,
        }


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    """One deterministic file in an export bundle."""

    relative_path: str
    media_type: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ExportManifest:
    """In-memory handle plus public-safe metadata for one report export."""

    export_id: str
    result_id: str
    directory: Path
    artifacts: Mapping[str, ReportArtifact]
    provenance: ReportProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifacts",
            MappingProxyType(dict(sorted(self.artifacts.items()))),
        )

    @property
    def engine_version(self) -> str:
        return self.provenance.engine_version

    @property
    def git_commit(self) -> str:
        return self.provenance.git_commit

    @property
    def data_hashes(self) -> Mapping[str, str]:
        return self.provenance.data_hashes

    @property
    def policy_cutoff(self) -> date:
        return self.provenance.policy_cutoff

    @property
    def actual_session_cutoff(self) -> date:
        return self.provenance.actual_session_cutoff

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.provenance.assumptions

    @property
    def limitations(self) -> tuple[str, ...]:
        return self.provenance.limitations

    def as_dict(self) -> dict[str, object]:
        return {
            "artifacts": {
                name: artifact.as_dict()
                for name, artifact in sorted(self.artifacts.items())
            },
            "export_id": self.export_id,
            "lineage": self.provenance.as_dict(),
            "result_id": self.result_id,
            "schema_version": "1.0",
        }
