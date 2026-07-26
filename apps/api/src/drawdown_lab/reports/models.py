"""Immutable report lineage and export manifest models."""

from __future__ import annotations

import hashlib
import json
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


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("provenance mapping keys must be strings")
        return MappingProxyType(
            {
                key: _freeze_json(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"unsupported provenance value: {type(value).__name__}")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ReportDataLineage:
    """Immutable catalog snapshot for one result input series."""

    provider: str
    fetched_at: datetime
    sha256: str
    policy_cutoff: date
    actual_session_cutoff: date
    classification: str

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        classification = self.classification.strip().lower()
        digest = self.sha256.strip().lower()
        if not provider:
            raise ValueError("data provider is required")
        if self.fetched_at.utcoffset() is None:
            raise ValueError("data fetched_at must be timezone-aware")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("data hash must be SHA-256")
        if self.actual_session_cutoff > self.policy_cutoff:
            raise ValueError("actual session cutoff cannot exceed policy cutoff")
        if classification not in {"actual", "synthetic"}:
            raise ValueError("data classification must be actual or synthetic")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "sha256", digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "actual_session_cutoff": self.actual_session_cutoff.isoformat(),
            "classification": self.classification,
            "fetched_at": self.fetched_at.isoformat(),
            "policy_cutoff": self.policy_cutoff.isoformat(),
            "provider": self.provider,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    """Complete, immutable lineage required to reproduce and interpret an export."""

    engine_version: str
    git_commit: str
    code_state: str
    data_lineage: Mapping[str, ReportDataLineage]
    result_sha256: str
    generated_at: datetime
    timezone: str
    parameters: Mapping[str, object]
    parameters_sha256: str
    analysis_boundary: Mapping[str, str]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        engine_version = self.engine_version.strip()
        git_commit = self.git_commit.strip().lower()
        timezone = self.timezone.strip()
        code_state = self.code_state.strip().lower()
        result_sha256 = self.result_sha256.strip().lower()
        parameters_sha256 = self.parameters_sha256.strip().lower()
        if not engine_version:
            raise ValueError("engine version is required")
        if not _GIT_COMMIT.fullmatch(git_commit):
            raise ValueError("git commit must be a hexadecimal commit identifier")
        if not timezone:
            raise ValueError("timezone is required")
        if code_state not in {"clean", "dirty", "injected"}:
            raise ValueError("code_state must be clean, dirty, or injected")
        if self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if _SHA256.fullmatch(result_sha256) is None:
            raise ValueError("result hash must be SHA-256")
        if _SHA256.fullmatch(parameters_sha256) is None:
            raise ValueError("parameters hash must be SHA-256")

        lineage = dict(sorted(self.data_lineage.items()))
        if not lineage:
            raise ValueError("at least one data lineage entry is required")
        for symbol, snapshot in lineage.items():
            if not symbol.strip():
                raise ValueError("data lineage symbols cannot be empty")
            if not isinstance(snapshot, ReportDataLineage):
                raise ValueError(f"invalid data lineage for {symbol}")

        parameters = _freeze_json(self.parameters)
        if not isinstance(parameters, Mapping) or not parameters:
            raise ValueError("persisted parameters are required")
        canonical_parameters = json.dumps(
            _thaw_json(parameters),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(canonical_parameters).hexdigest() != parameters_sha256:
            raise ValueError("parameters hash does not match persisted parameters")
        boundary = {
            key.strip(): value.strip()
            for key, value in sorted(self.analysis_boundary.items())
        }
        if not boundary or any(not key or not value for key, value in boundary.items()):
            raise ValueError("analysis boundary must contain non-empty entries")

        object.__setattr__(self, "engine_version", engine_version)
        object.__setattr__(self, "git_commit", git_commit)
        object.__setattr__(self, "result_sha256", result_sha256)
        object.__setattr__(self, "parameters_sha256", parameters_sha256)
        object.__setattr__(self, "timezone", timezone)
        object.__setattr__(self, "code_state", code_state)
        object.__setattr__(
            self,
            "data_lineage",
            MappingProxyType(lineage),
        )
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "analysis_boundary", MappingProxyType(boundary))
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

    @property
    def data_hashes(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                symbol: snapshot.sha256
                for symbol, snapshot in self.data_lineage.items()
            }
        )

    @property
    def policy_cutoff(self) -> date:
        return min(snapshot.policy_cutoff for snapshot in self.data_lineage.values())

    @property
    def actual_session_cutoff(self) -> date:
        return min(
            snapshot.actual_session_cutoff
            for snapshot in self.data_lineage.values()
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "actual_session_cutoff": self.actual_session_cutoff.isoformat(),
            "analysis_boundary": dict(self.analysis_boundary),
            "assumptions": list(self.assumptions),
            "data_hashes": dict(self.data_hashes),
            "data_lineage": {
                symbol: snapshot.as_dict()
                for symbol, snapshot in self.data_lineage.items()
            },
            "code_state": self.code_state,
            "engine_version": self.engine_version,
            "generated_at": self.generated_at.isoformat(),
            "git_commit": self.git_commit,
            "limitations": list(self.limitations),
            "parameters": _thaw_json(self.parameters),
            "parameters_sha256": self.parameters_sha256,
            "policy_cutoff": self.policy_cutoff.isoformat(),
            "result_sha256": self.result_sha256,
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
