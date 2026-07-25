"""Fail-closed privacy scanning for report publication bundles."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


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
            r"(?i)(?:\b[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/][^\\/\s]+|"
            r"/(?:Users|etc|home|mnt|opt|private|root|srv|tmp|var|Volumes)/)"
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
            r"(?i)[\"'](?:strategy[_-]?name|strategy[_-]?notes?|"
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
            normalized_header = stripped.strip().lower().replace("-", "_")
            if row_number == 1 and (
                normalized_header in _PRIVATE_CSV_FIELDS
                or normalized_header.startswith("private_")
            ):
                findings.append(
                    PrivacyFinding(
                        code="private_field",
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


def _scan_file(path: Path, relative_path: str) -> tuple[PrivacyFinding, ...]:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return (
            PrivacyFinding(
                code="binary_file",
                relative_path=relative_path,
                line=1,
                column=1,
            ),
        )

    findings: list[PrivacyFinding] = []
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
            json.loads(text)
        except json.JSONDecodeError as error:
            findings.append(
                PrivacyFinding(
                    code="invalid_json",
                    relative_path=relative_path,
                    line=error.lineno,
                    column=error.colno,
                )
            )
    return tuple(findings)


def privacy_scan(path: Path) -> PrivacyScanResult:
    """Scan a file or directory and allow publication only when no finding exists."""

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
        files = tuple(
            item
            for item in sorted(candidate.rglob("*"), key=lambda item: item.as_posix())
            if item.is_file() or item.is_symlink()
        )

    scanned_files = 0
    for file_path in files:
        relative_path = file_path.relative_to(root).as_posix()
        for code, pattern in _TEXT_PATTERNS:
            findings.extend(
                _finding(code, relative_path, relative_path, match.start())
                for match in pattern.finditer(relative_path)
            )
        if file_path.is_symlink():
            findings.append(
                PrivacyFinding(
                    code="symlink",
                    relative_path=relative_path,
                    line=1,
                    column=1,
                )
            )
            continue
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
