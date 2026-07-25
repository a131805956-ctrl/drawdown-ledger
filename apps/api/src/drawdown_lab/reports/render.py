"""Deterministic HTML, JSON, and CSV research report rendering."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from drawdown_lab.reports.models import (
    ExportManifest,
    ReportArtifact,
    ReportProvenance,
)
from drawdown_lab.storage.jobs import ResultRecord

_SUPPORTED_FORMATS = frozenset({"csv", "html", "json"})
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DISCLAIMER = (
    "This report is historical research, not personalized investment advice "
    "or a guarantee of future performance."
)
_MEDIA_TYPES = {
    "events_csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "trades_csv": "text/csv; charset=utf-8",
}


class ResultSource(Protocol):
    """Trusted persisted-result boundary used by the report application service."""

    def get_result(self, result_id: str) -> ResultRecord: ...


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Report payload cannot contain non-finite floats")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Report datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Report mapping keys must be strings")
            normalized[key] = _jsonable(item)
        return dict(sorted(normalized.items()))
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, str),
    ):
        return [_jsonable(item) for item in value]
    raise TypeError(f"Unsupported report payload type: {type(value).__name__}")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _csv_cell(value: object) -> str:
    normalized = _jsonable(value)
    if normalized is None:
        return ""
    if isinstance(normalized, (dict, list)):
        return json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    if isinstance(normalized, bool):
        return "true" if normalized else "false"
    return str(normalized)


def _csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    normalized_rows = [dict(row) for row in rows]
    fields = sorted({key for row in normalized_rows for key in row})
    stream = io.StringIO(newline="")
    if fields:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized_rows:
            writer.writerow({field: _csv_cell(row.get(field)) for field in fields})
    return stream.getvalue().encode("utf-8")


def _template_environment() -> Environment:
    package_template_root = Path(__file__).parents[1] / "templates"
    checkout_template_root = Path(__file__).parents[3] / "templates"
    return Environment(
        loader=FileSystemLoader(
            [str(package_template_root), str(checkout_template_root)]
        ),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        newline_sequence="\n",
    )


def _artifact(relative_path: str, media_type: str, content: bytes) -> ReportArtifact:
    return ReportArtifact(
        relative_path=relative_path,
        media_type=media_type,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
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


def export_report(
    result_id: str,
    formats: Sequence[str] = ("html", "json", "csv"),
    *,
    output_root: Path = Path("reports/private"),
    provenance: ReportProvenance,
    result_source: ResultSource,
) -> ExportManifest:
    """Export a deterministic private report bundle for one explicit result ID."""

    normalized_result_id = _validate_identifier(result_id, "result_id")
    requested_formats = frozenset(item.lower() for item in formats)
    unsupported = sorted(requested_formats - _SUPPORTED_FORMATS)
    if unsupported:
        raise ValueError(f"Unsupported report format: {', '.join(unsupported)}")
    if not requested_formats:
        raise ValueError("At least one report format is required")

    record = result_source.get_result(normalized_result_id)
    if record.id != normalized_result_id:
        raise ValueError("Trusted result source returned a mismatched result ID")
    if not isinstance(record.payload, Mapping):
        raise ValueError("Stored result payload must be a mapping")
    result = record.payload
    events = _stored_rows(result, "events")
    trades = _stored_rows(result, "trades")
    normalized_title = f"{record.kind.replace('_', ' ').title()} research result"
    normalized_result = _jsonable(result)
    normalized_events = _jsonable(events)
    normalized_trades = _jsonable(trades)
    seed = {
        "disclaimer": _DISCLAIMER,
        "events": normalized_events,
        "formats": sorted(requested_formats),
        "lineage": provenance.as_dict(),
        "result": normalized_result,
        "result_id": normalized_result_id,
        "schema_version": "1.0",
        "stored_schema_version": record.schema_version,
        "title": normalized_title,
        "trades": normalized_trades,
    }
    export_id = f"export-{hashlib.sha256(_json_bytes(seed)).hexdigest()[:24]}"
    report_document = {
        **seed,
        "export_id": export_id,
    }

    contents: dict[str, tuple[str, bytes]] = {}
    if "json" in requested_formats:
        contents["json"] = ("report.json", _json_bytes(report_document))
    if "csv" in requested_formats:
        contents["events_csv"] = (
            "events.csv",
            _csv_bytes(events),
        )
        contents["trades_csv"] = (
            "trades.csv",
            _csv_bytes(trades),
        )
    if "html" in requested_formats:
        template = _template_environment().get_template("report.html.j2")
        html = template.render(
            disclaimer=_DISCLAIMER,
            events=normalized_events,
            lineage=provenance.as_dict(),
            report_json=json.dumps(
                normalized_result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            result_id=normalized_result_id,
            title=normalized_title,
            trades=normalized_trades,
        )
        contents["html"] = ("report.html", html.encode("utf-8"))

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
    directory.mkdir(parents=True, exist_ok=True)
    for name, (relative_path, content) in sorted(contents.items()):
        artifact_path = directory / relative_path
        if artifact_path.exists() and artifact_path.read_bytes() != content:
            raise FileExistsError(
                f"Deterministic export collision for {name}: {export_id}"
            )
        artifact_path.write_bytes(content)
    (directory / "manifest.json").write_bytes(_json_bytes(manifest.as_dict()))
    return manifest
