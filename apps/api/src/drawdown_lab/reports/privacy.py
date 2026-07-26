"""Fail-closed privacy scanning for report publication bundles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    code: str
    relative_path: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class PrivacyScanResult:
    allowed: bool
    findings: tuple[PrivacyFinding, ...]
    scanned_files: int


_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "absolute_local_path",
        re.compile(
            r"(?i)(?:\b[A-Z]:[\\/]|(?<!:)(?:\\\\|//)[^\\/\s]+[\\/][^\\/\s]+|"
            r"(?<![A-Za-z0-9/:])/(?!/)[A-Za-z0-9._~-]+"
            r"(?:/[A-Za-z0-9._~ -]+)+|(?<![A-Za-z0-9])~[\\/])"
        ),
    ),
    (
        "private_path",
        re.compile(
            r"(?i)(?:^|[\"'\s:(])(?:reports|results|strategies)[\\/]+private"
            r"(?:[\\/]|[\"'\s),}]|$)|"
            r"(?:^|[\\/])(?:\.worktrees|\.runtime)(?:[\\/]|$)"
        ),
    ),
    (
        "private_field",
        re.compile(
            r"(?i)[\"'](?:name|strategy[_-]?name|strategy[_-]?notes?|"
            r"user[_-]?notes?|owner[_-]?name|notes?|"
            r"private[_-][^\"']+)[\"']\s*:"
        ),
    ),
    (
        "secret",
        re.compile(
            r"(?i)(?:sk-(?:proj|live|test)-[A-Za-z0-9_-]{8,}|"
            r"github_pat_[A-Za-z0-9_]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|"
            r"AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
            r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
            r"[\"']?(?:api[_-]?key|access[_-]?token|password|secret(?:[_-]?key)?)"
            r"[\"']?\s*[:=])"
        ),
    ),
    (
        "active_content",
        re.compile(
            r"(?i)(?:<\s*(?:script|iframe|object|embed)\b|"
            r"\bjavascript\s*:|\bdata\s*:\s*text/html|"
            r"\bon(?:error|load|click|focus)\s*=)"
        ),
    ),
    (
        "unsafe_formula",
        re.compile(r"[\"']\s*:\s*[\"']\s*(?:=|\+|@)"),
    ),
    (
        "path_traversal",
        re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)"),
    ),
)

_PRIVATE_CSV_FIELDS = frozenset(
    {
        "name",
        "note",
        "notes",
        "owner_name",
        "strategy_name",
        "strategy_note",
        "strategy_notes",
        "user_note",
        "user_notes",
    }
)
_ALLOWED_EXPORT_ARTIFACTS: Mapping[str, tuple[str, str]] = {
    "candidates_csv": ("candidates.csv", "text/csv; charset=utf-8"),
    "html": ("report.html", "text/html; charset=utf-8"),
    "json": ("report.json", "application/json"),
    "recommendations_csv": ("recommendations.csv", "text/csv; charset=utf-8"),
}
_ALLOWED_SUFFIXES = frozenset({".csv", ".html", ".json"})
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_WINDOWS_REPARSE_POINT = 0x400
_PRIVATE_JSON_FIELDS = _PRIVATE_CSV_FIELDS | frozenset(
    {
        "firstname",
        "fullname",
        "lastname",
        "private_metadata",
        "username",
    }
)
_SECRET_JSON_FIELDS = frozenset(
    {
        "api_key",
        "access_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "secret_key",
        "token",
    }
)


def _location(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return line, column


def _finding(
    code: str,
    relative_path: str,
    text: str,
    offset: int,
) -> PrivacyFinding:
    line, column = _location(text, offset)
    return PrivacyFinding(
        code=code,
        relative_path=relative_path,
        line=line,
        column=column,
    )


def _is_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _normalized_field_name(value: str) -> str:
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value.strip())
    return re.sub(r"[^A-Za-z0-9]+", "_", snake_case).strip("_").lower()


def _is_private_field_name(value: str) -> bool:
    normalized = _normalized_field_name(value)
    return (
        normalized in _PRIVATE_JSON_FIELDS
        or normalized.startswith("private_")
        or normalized.endswith("_name")
    )


def _is_secret_field_name(value: str) -> bool:
    normalized = _normalized_field_name(value)
    collapsed = normalized.replace("_", "")
    return (
        normalized in _SECRET_JSON_FIELDS
        or normalized.endswith(
            (
                "_api_key",
                "_credential",
                "_credentials",
                "_password",
                "_secret",
                "_secret_key",
                "_token",
            )
        )
        or collapsed
        in {
            "accesstoken",
            "apikey",
            "authtoken",
            "refreshtoken",
            "secretkey",
            "sessiontoken",
        }
    )


def _scan_csv_content(
    text: str,
    relative_path: str,
) -> tuple[PrivacyFinding, ...]:
    findings: list[PrivacyFinding] = []
    for row_number, row in enumerate(csv.reader(text.splitlines()), start=1):
        for column_number, value in enumerate(row, start=1):
            stripped = value.lstrip()
            if not stripped:
                continue
            if row_number == 1:
                if _is_private_field_name(stripped):
                    findings.append(
                        PrivacyFinding(
                            code="private_field",
                            relative_path=relative_path,
                            line=row_number,
                            column=column_number,
                        )
                    )
                if _is_secret_field_name(stripped):
                    findings.append(
                        PrivacyFinding(
                            code="secret",
                            relative_path=relative_path,
                            line=row_number,
                            column=column_number,
                        )
                    )
            if stripped[0] in "=+@" or (
                stripped[0] == "-" and not _is_numeric(stripped)
            ):
                findings.append(
                    PrivacyFinding(
                        code="unsafe_formula",
                        relative_path=relative_path,
                        line=row_number,
                        column=column_number,
                    )
                )
    return tuple(findings)


def _contains_absolute_local_path(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme.lower() == "file"
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("~/", "~\\"))
    )


def _scan_decoded_json(
    value: object,
    relative_path: str,
) -> tuple[PrivacyFinding, ...]:
    findings: list[PrivacyFinding] = []

    def add(code: str) -> None:
        findings.append(_simple_finding(code, relative_path))

    def scan_text(text: str) -> None:
        if _contains_absolute_local_path(text):
            add("absolute_local_path")
        for code, pattern in _TEXT_PATTERNS:
            if code in {"absolute_local_path", "private_field", "unsafe_formula"}:
                continue
            if pattern.search(text):
                add(code)
        stripped = text.lstrip()
        if stripped and (
            stripped[0] in "=+@"
            or (stripped[0] == "-" and not _is_numeric(stripped))
        ):
            add("unsafe_formula")

    def walk(item: object) -> None:
        if isinstance(item, str):
            scan_text(item)
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str):
                    if _is_private_field_name(key):
                        add("private_field")
                    if _is_secret_field_name(key):
                        add("secret")
                    scan_text(key)
                walk(child)
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (bytes, bytearray, str),
        ):
            for child in item:
                walk(child)

    walk(value)
    return tuple(findings)


def _scan_file(path: Path, relative_path: str) -> tuple[PrivacyFinding, ...]:
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        return (
            PrivacyFinding(
                code="unsupported_artifact",
                relative_path=relative_path,
                line=1,
                column=1,
            ),
        )
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return (
            PrivacyFinding(
                code="binary_file",
                relative_path=relative_path,
                line=1,
                column=1,
            ),
        )

    findings: list[PrivacyFinding] = []
    if not text.strip():
        findings.append(_simple_finding("empty_artifact", relative_path))
    if "\0" in text:
        findings.append(_finding("nul_byte", relative_path, text, text.index("\0")))
    for code, pattern in _TEXT_PATTERNS:
        findings.extend(
            _finding(code, relative_path, text, match.start())
            for match in pattern.finditer(text)
        )
    if path.suffix.lower() == ".csv":
        findings.extend(_scan_csv_content(text, relative_path))
    if path.suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            findings.append(
                PrivacyFinding(
                    code="invalid_json",
                    relative_path=relative_path,
                    line=error.lineno,
                    column=error.colno,
                )
            )
        else:
            findings.extend(_scan_decoded_json(document, relative_path))
    return tuple(findings)


def _simple_finding(code: str, relative_path: str) -> PrivacyFinding:
    return PrivacyFinding(code=code, relative_path=relative_path, line=1, column=1)


def _link_code(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if attributes & _WINDOWS_REPARSE_POINT:
        return "reparse_point"
    return None


def _unsafe_path_component(path: Path) -> tuple[str, Path] | None:
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        code = _link_code(component)
        if code is not None:
            return code, component
    return None


def _walk_regular_files(
    root: Path,
) -> tuple[tuple[Path, ...], tuple[PrivacyFinding, ...]]:
    files: list[Path] = []
    findings: list[PrivacyFinding] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            findings.append(
                _simple_finding(
                    "unreadable_path",
                    directory.relative_to(root).as_posix() or ".",
                )
            )
            continue
        for entry in entries:
            item = Path(entry.path)
            relative_path = item.relative_to(root).as_posix()
            link_code = _link_code(item)
            if link_code is not None:
                findings.append(_simple_finding(link_code, relative_path))
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    findings.append(
                        _simple_finding("unexpected_directory", relative_path)
                    )
                    pending.append(item)
                elif entry.is_file(follow_symlinks=False):
                    files.append(item)
                else:
                    findings.append(_simple_finding("unsupported_file_type", relative_path))
            except OSError:
                findings.append(_simple_finding("unreadable_path", relative_path))
    return tuple(sorted(files, key=lambda item: item.as_posix())), tuple(findings)


def _safe_manifest_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and _SAFE_IDENTIFIER.fullmatch(value) is not None
        and ".." not in value
    )


def _read_manifest(path: Path) -> Mapping[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _parsed_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parsed_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _valid_lineage(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != {
        "actual_session_cutoff",
        "analysis_boundary",
        "assumptions",
        "code_state",
        "data_hashes",
        "data_lineage",
        "engine_version",
        "generated_at",
        "git_commit",
        "limitations",
        "parameters",
        "parameters_sha256",
        "policy_cutoff",
        "result_sha256",
        "timezone",
    }:
        return False
    engine_version = value.get("engine_version")
    git_commit = value.get("git_commit")
    code_state = value.get("code_state")
    result_sha256 = value.get("result_sha256")
    timezone = value.get("timezone")
    parameters = value.get("parameters")
    parameters_sha256 = value.get("parameters_sha256")
    assumptions = value.get("assumptions")
    limitations = value.get("limitations")
    boundary = value.get("analysis_boundary")
    hashes = value.get("data_hashes")
    snapshots = value.get("data_lineage")
    if (
        not isinstance(engine_version, str)
        or not engine_version.strip()
        or not isinstance(git_commit, str)
        or re.fullmatch(r"[0-9a-fA-F]{7,64}", git_commit) is None
        or code_state not in {"clean", "dirty", "injected"}
        or not isinstance(result_sha256, str)
        or _SHA256.fullmatch(result_sha256) is None
        or timezone != "UTC"
        or _parsed_aware_datetime(value.get("generated_at")) is None
        or not isinstance(parameters, Mapping)
        or not parameters
        or not isinstance(parameters_sha256, str)
        or _SHA256.fullmatch(parameters_sha256) is None
        or not isinstance(assumptions, Sequence)
        or isinstance(assumptions, (bytes, str))
        or not assumptions
        or any(
            not isinstance(item, str) or not item.strip()
            for item in assumptions
        )
        or not isinstance(limitations, Sequence)
        or isinstance(limitations, (bytes, str))
        or not limitations
        or any(
            not isinstance(item, str) or not item.strip()
            for item in limitations
        )
        or not isinstance(boundary, Mapping)
        or set(boundary)
        != {"formal_result", "synthetic_stress"}
        or boundary.get("formal_result") not in {"actual", "synthetic"}
        or boundary.get("synthetic_stress")
        not in {"not_requested", "separate_stress_only"}
        or not isinstance(hashes, Mapping)
        or not hashes
        or not isinstance(snapshots, Mapping)
        or set(hashes) != set(snapshots)
    ):
        return False
    try:
        canonical_parameters = json.dumps(
            parameters,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    if hashlib.sha256(canonical_parameters).hexdigest() != parameters_sha256:
        return False

    policy_dates: list[date] = []
    actual_dates: list[date] = []
    for symbol, raw_snapshot in snapshots.items():
        digest = hashes.get(symbol)
        if (
            not isinstance(symbol, str)
            or not symbol.strip()
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or not isinstance(raw_snapshot, Mapping)
            or set(raw_snapshot)
            != {
                "actual_session_cutoff",
                "classification",
                "fetched_at",
                "policy_cutoff",
                "provider",
                "sha256",
            }
            or raw_snapshot.get("sha256") != digest
            or not isinstance(raw_snapshot.get("provider"), str)
            or not str(raw_snapshot.get("provider")).strip()
            or _parsed_aware_datetime(raw_snapshot.get("fetched_at")) is None
            or raw_snapshot.get("classification") not in {"actual", "synthetic"}
            or raw_snapshot.get("classification")
            != boundary.get("formal_result")
        ):
            return False
        policy = _parsed_date(raw_snapshot.get("policy_cutoff"))
        actual = _parsed_date(raw_snapshot.get("actual_session_cutoff"))
        if policy is None or actual is None or actual > policy:
            return False
        policy_dates.append(policy)
        actual_dates.append(actual)

    return (
        _parsed_date(value.get("policy_cutoff")) == min(policy_dates)
        and _parsed_date(value.get("actual_session_cutoff")) == min(actual_dates)
    )


def _export_manifest_findings(
    root: Path,
    manifest: Mapping[str, object],
    actual_paths: frozenset[str],
) -> tuple[PrivacyFinding, ...]:
    findings: list[PrivacyFinding] = []
    if set(manifest) != {
        "artifacts",
        "export_id",
        "lineage",
        "result_id",
        "schema_version",
    }:
        findings.append(_simple_finding("invalid_manifest", "manifest.json"))
    if manifest.get("schema_version") != "1.0":
        findings.append(_simple_finding("invalid_manifest", "manifest.json"))
    if not _safe_manifest_identifier(manifest.get("export_id")):
        findings.append(_simple_finding("invalid_export_id", "manifest.json"))
    if not _safe_manifest_identifier(manifest.get("result_id")):
        findings.append(_simple_finding("invalid_result_id", "manifest.json"))
    if not _valid_lineage(manifest.get("lineage")):
        findings.append(_simple_finding("invalid_lineage", "manifest.json"))

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        findings.append(_simple_finding("invalid_manifest", "manifest.json"))
        return tuple(findings)

    expected_paths = {"manifest.json"}
    validated: list[tuple[str, int, str]] = []
    for name, raw_artifact in artifacts.items():
        expected = _ALLOWED_EXPORT_ARTIFACTS.get(str(name))
        if expected is None or not isinstance(raw_artifact, Mapping):
            findings.append(_simple_finding("unsupported_artifact", "manifest.json"))
            continue
        expected_path, expected_media_type = expected
        if set(raw_artifact) != {
            "media_type",
            "relative_path",
            "sha256",
            "size_bytes",
        }:
            findings.append(
                _simple_finding("invalid_artifact_metadata", "manifest.json")
            )
            continue
        relative_path = raw_artifact.get("relative_path")
        media_type = raw_artifact.get("media_type")
        digest = raw_artifact.get("sha256")
        size_bytes = raw_artifact.get("size_bytes")
        if (
            relative_path != expected_path
            or media_type != expected_media_type
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
        ):
            findings.append(_simple_finding("invalid_artifact_metadata", "manifest.json"))
            continue
        expected_paths.add(expected_path)
        validated.append((expected_path, size_bytes, digest.lower()))

    artifact_names = set(artifacts)
    has_csv_pair = {
        "candidates_csv",
        "recommendations_csv",
    } <= artifact_names
    if (
        "json" not in artifact_names
        or ("candidates_csv" in artifact_names)
        != ("recommendations_csv" in artifact_names)
    ):
        findings.append(_simple_finding("invalid_artifact_set", "manifest.json"))
    if actual_paths != frozenset(expected_paths):
        findings.append(_simple_finding("artifact_set_mismatch", "manifest.json"))
    artifact_contents: dict[str, bytes] = {}
    report_document: Mapping[str, object] | None = None
    for relative_path, expected_size, expected_digest in validated:
        artifact_path = root / relative_path
        try:
            content = artifact_path.read_bytes()
        except OSError:
            findings.append(_simple_finding("missing_artifact", relative_path))
            continue
        artifact_contents[relative_path] = content
        if len(content) != expected_size:
            findings.append(_simple_finding("artifact_size_mismatch", relative_path))
        if hashlib.sha256(content).hexdigest() != expected_digest:
            findings.append(_simple_finding("artifact_hash_mismatch", relative_path))
        if relative_path == "report.json":
            try:
                parsed_report = json.loads(content.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed_report = None
            if isinstance(parsed_report, Mapping):
                report_document = parsed_report
            if (
                not isinstance(report_document, Mapping)
                or report_document.get("export_id") != manifest.get("export_id")
                or report_document.get("result_id") != manifest.get("result_id")
            ):
                findings.append(
                    _simple_finding("artifact_identifier_mismatch", relative_path)
                )
                continue
            if set(report_document) != {
                "candidates",
                "disclaimer",
                "export_id",
                "formats",
                "lineage",
                "recommendations",
                "result",
                "result_id",
                "schema_version",
                "stored_schema_version",
                "title",
            }:
                findings.append(
                    _simple_finding("invalid_report_schema", relative_path)
                )
            if (
                report_document.get("schema_version") != "1.0"
                or report_document.get("stored_schema_version") != "1.0"
                or not isinstance(report_document.get("title"), str)
                or not str(report_document.get("title")).strip()
                or not isinstance(report_document.get("disclaimer"), str)
                or not str(report_document.get("disclaimer")).strip()
                or not isinstance(report_document.get("candidates"), Sequence)
                or isinstance(
                    report_document.get("candidates"),
                    (bytes, str),
                )
                or not isinstance(
                    report_document.get("recommendations"),
                    Sequence,
                )
                or isinstance(
                    report_document.get("recommendations"),
                    (bytes, str),
                )
            ):
                findings.append(
                    _simple_finding("invalid_report_schema", relative_path)
                )
            if report_document.get("lineage") != manifest.get("lineage"):
                findings.append(
                    _simple_finding("artifact_lineage_mismatch", relative_path)
                )
            expected_formats = ["json"]
            if has_csv_pair:
                expected_formats.append("csv")
            if "html" in artifact_names:
                expected_formats.append("html")
            expected_formats.sort()
            if report_document.get("formats") != expected_formats:
                findings.append(
                    _simple_finding("artifact_formats_mismatch", relative_path)
                )
            result = report_document.get("result")
            lineage = manifest.get("lineage")
            expected_result_hash = (
                lineage.get("result_sha256")
                if isinstance(lineage, Mapping)
                else None
            )
            try:
                canonical_result = json.dumps(
                    result,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError):
                canonical_result = b""
            if (
                not canonical_result
                or hashlib.sha256(canonical_result).hexdigest()
                != expected_result_hash
            ):
                findings.append(
                    _simple_finding("result_hash_mismatch", relative_path)
                )
            if not isinstance(result, Mapping):
                findings.append(
                    _simple_finding("invalid_report_schema", relative_path)
                )
            elif result.get("schema_version") != "1.0":
                findings.append(
                    _simple_finding("invalid_report_schema", relative_path)
                )
            elif (
                report_document.get("candidates")
                != result.get("candidates", [])
                or report_document.get("recommendations")
                != result.get("recommendations", [])
            ):
                findings.append(
                    _simple_finding("artifact_rows_mismatch", relative_path)
                )
    if report_document is not None:
        report_seed = dict(report_document)
        report_seed.pop("export_id", None)
        try:
            canonical_report_seed = (
                json.dumps(
                    report_seed,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            identity_contents = dict(artifact_contents)
            identity_contents["report.json"] = canonical_report_seed
            identity_seed = {
                "artifact_sha256": {
                    relative_path: hashlib.sha256(content).hexdigest()
                    for relative_path, content in sorted(identity_contents.items())
                },
                "report": report_seed,
            }
            identity_bytes = (
                json.dumps(
                    identity_seed,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            expected_export_id = (
                f"export-{hashlib.sha256(identity_bytes).hexdigest()[:24]}"
            )
        except (TypeError, ValueError):
            expected_export_id = ""
        if (
            expected_export_id != manifest.get("export_id")
            or expected_export_id != report_document.get("export_id")
        ):
            findings.append(
                _simple_finding("export_id_mismatch", "report.json")
            )
    return tuple(findings)


def _demo_manifest_findings(
    root: Path,
    manifest: Mapping[str, object],
    actual_paths: frozenset[str],
) -> tuple[PrivacyFinding, ...]:
    findings: list[PrivacyFinding] = []
    evidence_file = manifest.get("evidence_file")
    digest = manifest.get("evidence_sha256")
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("mode") != "static_demo"
        or manifest.get("live") is not False
        or not isinstance(evidence_file, str)
        or Path(evidence_file).name != evidence_file
        or Path(evidence_file).suffix.lower() != ".json"
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
    ):
        return (_simple_finding("invalid_manifest", "manifest.json"),)
    if actual_paths != frozenset({"manifest.json", evidence_file}):
        findings.append(_simple_finding("artifact_set_mismatch", "manifest.json"))
    try:
        content = (root / evidence_file).read_bytes()
    except OSError:
        findings.append(_simple_finding("missing_artifact", evidence_file))
    else:
        if hashlib.sha256(content).hexdigest() != digest.lower():
            findings.append(_simple_finding("artifact_hash_mismatch", evidence_file))
    return tuple(findings)


def _manifest_findings(
    root: Path,
    files: tuple[Path, ...],
) -> tuple[PrivacyFinding, ...]:
    actual_paths = frozenset(path.relative_to(root).as_posix() for path in files)
    manifest_path = root / "manifest.json"
    if "manifest.json" not in actual_paths:
        return (_simple_finding("missing_manifest", "manifest.json"),)
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return (_simple_finding("invalid_manifest", "manifest.json"),)
    if manifest.get("mode") == "static_demo":
        return _demo_manifest_findings(root, manifest, actual_paths)
    return _export_manifest_findings(root, manifest, actual_paths)


def privacy_scan(path: Path) -> PrivacyScanResult:
    """Scan a file or directory and allow publication only when no finding exists."""

    unsafe_component = _unsafe_path_component(path)
    if unsafe_component is not None:
        code, component = unsafe_component
        finding = _simple_finding(code, component.name or ".")
        return PrivacyScanResult(False, (finding,), 0)

    candidate = path.resolve()
    if not candidate.exists():
        finding = PrivacyFinding(
            code="missing_path",
            relative_path=path.name or ".",
            line=1,
            column=1,
        )
        return PrivacyScanResult(False, (finding,), 0)

    findings: list[PrivacyFinding] = []
    files: tuple[Path, ...]
    if candidate.is_file():
        files = (candidate,)
        root = candidate.parent
    else:
        root = candidate
        files, path_findings = _walk_regular_files(candidate)
        findings.extend(path_findings)
        findings.extend(_manifest_findings(root, files))

    scanned_files = 0
    for file_path in files:
        relative_path = file_path.relative_to(root).as_posix()
        for code, pattern in _TEXT_PATTERNS:
            findings.extend(
                _finding(code, relative_path, relative_path, match.start())
                for match in pattern.finditer(relative_path)
            )
        scanned_files += 1
        findings.extend(_scan_file(file_path, relative_path))

    ordered = tuple(
        sorted(
            set(findings),
            key=lambda item: (
                item.relative_path,
                item.line,
                item.column,
                item.code,
            ),
        )
    )
    return PrivacyScanResult(not ordered, ordered, scanned_files)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed privacy scan for a report publication bundle."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    result = privacy_scan(args.path)
    summary = {
        "allowed": result.allowed,
        "findings": [
            {
                "code": finding.code,
                "column": finding.column,
                "line": finding.line,
                "relative_path": finding.relative_path,
            }
            for finding in result.findings
        ],
        "scanned_files": result.scanned_files,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
