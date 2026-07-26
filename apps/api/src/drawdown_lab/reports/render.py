"""Deterministic HTML, JSON, and CSV research report rendering."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from drawdown_lab.data.catalog import DataIntegrityError
from drawdown_lab.reports.canonical import (
    CANDIDATE_FIELDS as _CANDIDATE_FIELDS,
)
from drawdown_lab.reports.canonical import (
    RECOMMENDATION_FIELDS as _RECOMMENDATION_FIELDS,
)
from drawdown_lab.reports.canonical import (
    TRADE_FIELDS as _TRADE_FIELDS,
)
from drawdown_lab.reports.canonical import (
    canonical_csv_bytes as _csv_bytes,
)
from drawdown_lab.reports.canonical import (
    canonical_json_bytes as _json_bytes,
)
from drawdown_lab.reports.canonical import (
    canonical_jsonable as _jsonable,
)
from drawdown_lab.reports.models import (
    ExportManifest,
    ReportArtifact,
    ReportDataLineage,
    ReportProvenance,
)
from drawdown_lab.reports.render_html import canonical_report_html
from drawdown_lab.storage.jobs import JobStatus, JobStore, ResultRecord

_SUPPORTED_FORMATS = frozenset({"csv", "html", "json"})
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DISCLAIMER = (
    "This report is historical research, not personalized investment advice "
    "or a guarantee of future performance."
)
_MEDIA_TYPES = {
    "candidates_csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "recommendations_csv": "text/csv; charset=utf-8",
    "trades_csv": "text/csv; charset=utf-8",
}
def _artifact(relative_path: str, media_type: str, content: bytes) -> ReportArtifact:
    return ReportArtifact(
        relative_path=relative_path,
        media_type=media_type,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def _validate_existing_bundle(
    directory: Path,
    expected: Mapping[str, bytes],
    export_id: str,
) -> None:
    children = tuple(directory.rglob("*"))
    actual_files = {
        path.relative_to(directory).as_posix()
        for path in children
        if path.is_file()
    }
    if any(path.is_dir() for path in children) or actual_files != set(expected):
        raise FileExistsError(
            f"Deterministic export collision for bundle: {export_id}"
        )
    for relative_path, content in expected.items():
        if (directory / relative_path).read_bytes() != content:
            raise FileExistsError(
                f"Deterministic export collision for {relative_path}: {export_id}"
            )


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized) or ".." in normalized:
        raise ValueError(f"{field_name} contains unsafe characters")
    return normalized


def _stored_rows(
    payload: Mapping[str, object],
    field_name: str,
) -> tuple[Mapping[str, object], ...]:
    value = payload.get(field_name, ())
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray, str)):
        raise ValueError(f"Stored result {field_name} must be a sequence")
    rows: list[Mapping[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"Stored result {field_name} rows must be mappings")
        if any(not isinstance(key, str) for key in row):
            raise ValueError(f"Stored result {field_name} keys must be strings")
        rows.append(row)
    return tuple(rows)


def _render_report(
    record: ResultRecord,
    provenance: ReportProvenance,
    output_root: Path,
    formats: Sequence[str] = ("html", "json", "csv"),
) -> ExportManifest:
    """Render one already authenticated persisted result into a private bundle."""

    normalized_result_id = _validate_identifier(record.id, "result_id")
    requested_formats = frozenset(item.lower() for item in formats)
    unsupported = sorted(requested_formats - _SUPPORTED_FORMATS)
    if unsupported:
        raise ValueError(f"Unsupported report format: {', '.join(unsupported)}")
    if not requested_formats:
        raise ValueError("At least one report format is required")
    requested_formats = requested_formats | {"json"}

    if not isinstance(record.payload, Mapping):
        raise ValueError("Stored result payload must be a mapping")
    result = record.payload
    candidates = _stored_rows(result, "candidates")
    recommendations = _stored_rows(result, "recommendations")
    trades = _stored_rows(result, "trades")
    normalized_title = f"{record.kind.replace('_', ' ').title()} research result"
    normalized_result = _jsonable(result)
    normalized_candidates = _jsonable(candidates)
    normalized_recommendations = _jsonable(recommendations)
    normalized_trades = _jsonable(trades)
    seed = {
        "disclaimer": _DISCLAIMER,
        "candidates": normalized_candidates,
        "formats": sorted(requested_formats),
        "lineage": provenance.as_dict(),
        "result": normalized_result,
        "result_id": normalized_result_id,
        "schema_version": "1.0",
        "stored_schema_version": record.schema_version,
        "title": normalized_title,
        "recommendations": normalized_recommendations,
        "trades": normalized_trades,
    }
    contents: dict[str, tuple[str, bytes]] = {}
    if "csv" in requested_formats:
        contents["candidates_csv"] = (
            "candidates.csv",
            _csv_bytes(candidates, empty_fields=_CANDIDATE_FIELDS),
        )
        contents["recommendations_csv"] = (
            "recommendations.csv",
            _csv_bytes(
                recommendations,
                empty_fields=_RECOMMENDATION_FIELDS,
            ),
        )
        contents["trades_csv"] = (
            "trades.csv",
            _csv_bytes(trades, empty_fields=_TRADE_FIELDS),
        )
    if "html" in requested_formats:
        contents["html"] = (
            "report.html",
            canonical_report_html(seed),
        )

    identity_contents = {
        relative_path: content
        for relative_path, content in contents.values()
    }
    if "json" in requested_formats:
        identity_contents["report.json"] = _json_bytes(seed)
    identity_seed = {
        "artifact_sha256": {
            relative_path: hashlib.sha256(content).hexdigest()
            for relative_path, content in sorted(identity_contents.items())
        },
        "report": seed,
    }
    export_id = (
        f"export-{hashlib.sha256(_json_bytes(identity_seed)).hexdigest()[:24]}"
    )
    report_document = {
        **seed,
        "export_id": export_id,
    }
    if "json" in requested_formats:
        contents["json"] = ("report.json", _json_bytes(report_document))

    artifacts = {
        name: _artifact(relative_path, _MEDIA_TYPES[name], content)
        for name, (relative_path, content) in sorted(contents.items())
    }
    directory = output_root.resolve() / export_id
    manifest = ExportManifest(
        export_id=export_id,
        result_id=normalized_result_id,
        directory=directory,
        artifacts=artifacts,
        provenance=provenance,
    )
    expected = {
        relative_path: content
        for relative_path, content in contents.values()
    }
    expected["manifest.json"] = _json_bytes(manifest.as_dict())
    if directory.exists():
        _validate_existing_bundle(directory, expected, export_id)
        return manifest

    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = directory.parent / f".{export_id}.{uuid4().hex}.tmp"
    temporary.mkdir()
    try:
        for relative_path, content in sorted(expected.items()):
            (temporary / relative_path).write_bytes(content)
        try:
            os.replace(temporary, directory)
        except OSError:
            if not directory.exists():
                raise
            _validate_existing_bundle(directory, expected, export_id)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    engine_version: str
    git_commit: str
    code_state: str


def _engine_version(repository_root: Path | None) -> str:
    try:
        return importlib.metadata.version("drawdown-lab")
    except importlib.metadata.PackageNotFoundError:
        if repository_root is None:
            raise ValueError(
                "engine_version build metadata is required outside an installed package"
            )
        configuration = tomllib.loads(
            (repository_root / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = configuration.get("project", {}).get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Unable to determine the report engine version")
        return version.strip()


def _git_commit(repository_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Unable to resolve the trusted repository commit") from error
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        raise ValueError("Trusted repository returned an invalid commit identifier")
    return commit.lower()


def resolve_runtime_identity(
    *,
    repository_root: Path | None,
    engine_version: str | None = None,
    git_commit: str | None = None,
) -> RuntimeIdentity:
    normalized_engine = (
        engine_version.strip()
        if engine_version is not None
        else _engine_version(repository_root)
    )
    if not normalized_engine:
        raise ValueError("engine_version build metadata is required")
    if git_commit is not None:
        normalized_commit = git_commit.strip().lower()
        code_state = "injected"
    else:
        if repository_root is None:
            raise ValueError(
                "git_commit build metadata is required outside a source checkout"
            )
        normalized_commit = _git_commit(repository_root)
        try:
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository_root),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Unable to determine trusted source tree state") from error
        code_state = "dirty" if status.stdout.strip() else "clean"
    if re.fullmatch(r"[0-9a-f]{7,64}", normalized_commit) is None:
        raise ValueError("git_commit must be a hexadecimal commit identifier")
    return RuntimeIdentity(
        engine_version=normalized_engine,
        git_commit=normalized_commit,
        code_state=code_state,
    )


def _validate_persisted_job(
    job_store: JobStore,
    record: ResultRecord,
    *,
    parameters_sha256: str,
) -> None:
    job = job_store.get(record.job_id)
    if (
        job.status is not JobStatus.SUCCEEDED
        or job.result_id != record.id
        or job.kind != record.kind
    ):
        raise ValueError("Result is not bound to a succeeded persisted job")
    try:
        persisted = json.loads(job.request_json)
    except json.JSONDecodeError as error:
        raise DataIntegrityError("Persisted job request is invalid JSON") from error
    if (
        not isinstance(persisted, Mapping)
        or persisted.get("schema_version") != "1.0"
        or not isinstance(persisted.get("request"), Mapping)
    ):
        raise DataIntegrityError("Persisted job request lineage is incomplete")
    parameters = persisted["request"]
    if not isinstance(parameters, Mapping):
        raise DataIntegrityError("Persisted job parameters must be a mapping")
    canonical_parameters = json.dumps(
        parameters,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(canonical_parameters).hexdigest() != parameters_sha256:
        raise DataIntegrityError(
            "Persisted job parameters do not match result-time lineage"
        )


def _result_symbols(payload: Mapping[str, object]) -> tuple[str, str, str]:
    raw_provenance = payload.get("provenance")
    if not isinstance(raw_provenance, Mapping):
        raise ValueError("Persisted result provenance is missing")
    prototype_symbol = raw_provenance.get("prototype_symbol")
    target_symbol = raw_provenance.get("target_symbol")
    source_kind = raw_provenance.get("source_kind")
    if (
        not isinstance(prototype_symbol, str)
        or not prototype_symbol.strip()
        or not isinstance(target_symbol, str)
        or not target_symbol.strip()
        or source_kind not in {"actual", "synthetic"}
    ):
        raise ValueError("Persisted result data boundary is incomplete")
    return prototype_symbol.strip(), target_symbol.strip(), str(source_kind)


def _analysis_boundary(
    payload: Mapping[str, object],
    source_kind: str,
) -> Mapping[str, str]:
    stress = payload.get("synthetic_stress")
    if not isinstance(stress, Mapping) or not isinstance(stress.get("requested"), bool):
        raise ValueError("Persisted result synthetic boundary is missing")
    return {
        "formal_result": source_kind,
        "synthetic_stress": (
            "separate_stress_only" if stress["requested"] else "not_requested"
        ),
    }


@dataclass(frozen=True, slots=True)
class _StoredResultLineage:
    engine_version: str
    git_commit: str
    code_state: str
    data_lineage: Mapping[str, ReportDataLineage]
    result_sha256: str
    generated_at: datetime
    timezone: str
    parameters: Mapping[str, object]
    parameters_sha256: str


def _persisted_result_lineage(
    record: ResultRecord,
    *,
    symbols: tuple[str, ...],
    source_kind: str,
) -> _StoredResultLineage:
    value = record.lineage
    required_fields = {
        "code_state",
        "data_lineage",
        "engine_version",
        "generated_at",
        "git_commit",
        "parameters",
        "parameters_sha256",
        "result_sha256",
        "schema_version",
        "timezone",
    }
    if not isinstance(value, Mapping) or set(value) != required_fields:
        raise DataIntegrityError("Persisted result lineage is missing or incomplete")
    if value.get("schema_version") != "1.0":
        raise DataIntegrityError("Persisted result lineage schema is unsupported")
    engine_version = value.get("engine_version")
    git_commit = value.get("git_commit")
    code_state = value.get("code_state")
    timezone = value.get("timezone")
    expected_result_hash = value.get("result_sha256")
    parameters = value.get("parameters")
    parameters_sha256 = value.get("parameters_sha256")
    raw_data_lineage = value.get("data_lineage")
    if (
        not isinstance(engine_version, str)
        or not isinstance(git_commit, str)
        or not isinstance(code_state, str)
        or timezone != "UTC"
        or not isinstance(expected_result_hash, str)
        or not isinstance(parameters, Mapping)
        or not parameters
        or not isinstance(parameters_sha256, str)
        or not isinstance(raw_data_lineage, Mapping)
        or set(raw_data_lineage) != set(symbols)
    ):
        raise DataIntegrityError("Persisted result lineage is invalid")
    actual_result_hash = hashlib.sha256(record.raw_json.encode("utf-8")).hexdigest()
    if expected_result_hash.lower() != actual_result_hash:
        raise DataIntegrityError("Persisted result hash does not match its lineage")
    try:
        canonical_parameters = json.dumps(
            parameters,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DataIntegrityError("Persisted result parameters are invalid") from error
    if hashlib.sha256(canonical_parameters).hexdigest() != parameters_sha256:
        raise DataIntegrityError(
            "Persisted parameters do not match their result-time hash"
        )
    try:
        generated_at = datetime.fromisoformat(str(value.get("generated_at")))
        record_created_at = datetime.fromisoformat(record.created_at)
    except ValueError as error:
        raise DataIntegrityError("Persisted result time is invalid") from error
    if (
        generated_at.utcoffset() is None
        or record_created_at.utcoffset() is None
        or generated_at != record_created_at
    ):
        raise DataIntegrityError("Persisted result time does not match its lineage")

    data_lineage: dict[str, ReportDataLineage] = {}
    snapshot_fields = {
        "actual_session_cutoff",
        "classification",
        "fetched_at",
        "policy_cutoff",
        "provider",
        "sha256",
    }
    try:
        for symbol in symbols:
            raw_snapshot = raw_data_lineage[symbol]
            if not isinstance(raw_snapshot, Mapping) or set(raw_snapshot) != snapshot_fields:
                raise DataIntegrityError(
                    f"Persisted data lineage is incomplete for {symbol}"
                )
            if raw_snapshot.get("classification") != source_kind:
                raise DataIntegrityError(
                    f"Persisted data classification conflicts for {symbol}"
                )
            data_lineage[symbol] = ReportDataLineage(
                provider=str(raw_snapshot["provider"]),
                fetched_at=datetime.fromisoformat(str(raw_snapshot["fetched_at"])),
                sha256=str(raw_snapshot["sha256"]),
                policy_cutoff=date.fromisoformat(str(raw_snapshot["policy_cutoff"])),
                actual_session_cutoff=date.fromisoformat(
                    str(raw_snapshot["actual_session_cutoff"])
                ),
                classification=str(raw_snapshot["classification"]),
            )
    except (KeyError, TypeError, ValueError) as error:
        raise DataIntegrityError("Persisted data lineage is invalid") from error
    return _StoredResultLineage(
        engine_version=engine_version,
        git_commit=git_commit,
        code_state=code_state,
        data_lineage=data_lineage,
        result_sha256=actual_result_hash,
        generated_at=generated_at,
        timezone=str(timezone),
        parameters=parameters,
        parameters_sha256=parameters_sha256,
    )


class ReportExporter:
    """Application-owned export service with no caller payload or lineage inputs."""

    def __init__(
        self,
        *,
        job_store: JobStore,
        output_root: Path,
    ) -> None:
        self.job_store = job_store
        self.output_root = output_root.resolve()

    def export_report(
        self,
        result_id: str,
        formats: Sequence[str] = ("html", "json", "csv"),
    ) -> ExportManifest:
        normalized_result_id = _validate_identifier(result_id, "result_id")
        record = self.job_store.get_result(normalized_result_id)
        if record.schema_version != "1.0":
            raise ValueError("Unsupported persisted result schema version")
        if not isinstance(record.payload, Mapping):
            raise ValueError("Stored result payload must be a mapping")
        prototype_symbol, target_symbol, source_kind = _result_symbols(record.payload)
        symbols = tuple(dict.fromkeys((prototype_symbol, target_symbol)))
        lineage = _persisted_result_lineage(
            record,
            symbols=symbols,
            source_kind=source_kind,
        )
        _validate_persisted_job(
            self.job_store,
            record,
            parameters_sha256=lineage.parameters_sha256,
        )
        provenance = ReportProvenance(
            engine_version=lineage.engine_version,
            git_commit=lineage.git_commit,
            code_state=lineage.code_state,
            data_lineage=lineage.data_lineage,
            result_sha256=lineage.result_sha256,
            generated_at=lineage.generated_at,
            timezone=lineage.timezone,
            parameters=lineage.parameters,
            parameters_sha256=lineage.parameters_sha256,
            analysis_boundary=_analysis_boundary(record.payload, source_kind),
            assumptions=(
                "Signals are observed at the close and execute no earlier than the next open.",
            ),
            limitations=(
                "Historical research is not a guarantee of future performance.",
                "Synthetic stress results, when requested, remain separate from actual history.",
            ),
        )
        manifest = _render_report(record, provenance, self.output_root, formats)
        manifest_document = manifest.as_dict()
        artifacts = manifest_document["artifacts"]
        lineage_document = manifest_document["lineage"]
        if not isinstance(artifacts, Mapping) or not isinstance(
            lineage_document,
            Mapping,
        ):
            raise RuntimeError("Rendered report manifest is invalid")
        self.job_store.mark_report_exported(
            normalized_result_id,
            content={
                "artifacts": artifacts,
                "export_id": manifest.export_id,
                "lineage": lineage_document,
                "message": "Report export is ready.",
                "optimization": record.payload,
                "result_id": normalized_result_id,
                "status": "exported",
            },
        )
        return manifest
