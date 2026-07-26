"""Validate a collection of public report bundles and build its landing page."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drawdown_lab.reports.privacy import privacy_scan

_EXPORT_ID = re.compile(r"^export-[0-9a-f]{24}$")


class PublicationCollectionError(ValueError):
    """A published collection is not a set of validated export bundles."""


@dataclass(frozen=True, slots=True)
class PublishedReport:
    export_id: str
    result_id: str
    title: str
    generated_at: str
    href: str
    formats: tuple[str, ...]


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _load_mapping(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicationCollectionError(f"invalid {label}: {path.name}") from error
    if not isinstance(payload, Mapping):
        raise PublicationCollectionError(f"invalid {label}: {path.name}")
    return payload


def _published_report(bundle: Path) -> PublishedReport:
    manifest = _load_mapping(bundle / "manifest.json", label="manifest")
    document = _load_mapping(bundle / "report.json", label="report")
    export_id = manifest.get("export_id")
    result_id = manifest.get("result_id")
    if export_id != bundle.name or not isinstance(result_id, str):
        raise PublicationCollectionError(
            f"bundle identity mismatch: {bundle.name}"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PublicationCollectionError(f"invalid artifacts: {bundle.name}")
    formats = tuple(sorted(str(name) for name in artifacts))
    html_artifact = artifacts.get("html")
    if isinstance(html_artifact, Mapping):
        relative_path = html_artifact.get("relative_path")
        if relative_path != "report.html":
            raise PublicationCollectionError(
                f"invalid HTML artifact: {bundle.name}"
            )
        href = f"published/{export_id}/report.html"
    else:
        json_artifact = artifacts.get("json")
        if (
            not isinstance(json_artifact, Mapping)
            or json_artifact.get("relative_path") != "report.json"
        ):
            raise PublicationCollectionError(
                f"missing readable artifact: {bundle.name}"
            )
        href = f"published/{export_id}/report.json"
    title = document.get("title")
    lineage = manifest.get("lineage")
    generated_at = (
        lineage.get("generated_at")
        if isinstance(lineage, Mapping)
        else None
    )
    return PublishedReport(
        export_id=export_id,
        result_id=result_id,
        title=title if isinstance(title, str) and title.strip() else result_id,
        generated_at=generated_at if isinstance(generated_at, str) else "",
        href=href,
        formats=formats,
    )


def validate_published_collection(
    collection: Path,
) -> tuple[PublishedReport, ...]:
    if not os.path.lexists(collection):
        return ()
    if _is_link_like(collection) or not collection.is_dir():
        raise PublicationCollectionError("invalid published collection root")
    reports: list[PublishedReport] = []
    for entry in sorted(collection.iterdir(), key=lambda path: path.name):
        if _is_link_like(entry):
            raise PublicationCollectionError(
                f"linked collection entry: {entry.name}"
            )
        if not entry.is_dir() or not _EXPORT_ID.fullmatch(entry.name):
            raise PublicationCollectionError(
                f"unexpected collection entry: {entry.name}"
            )
        scan = privacy_scan(entry)
        if not scan.allowed:
            codes = ",".join(sorted({finding.code for finding in scan.findings}))
            raise PublicationCollectionError(
                f"privacy validation failed for {entry.name}: {codes}"
            )
        reports.append(_published_report(entry))
    return tuple(reports)


def _render_index(reports: Sequence[PublishedReport]) -> str:
    if reports:
        cards = "\n".join(
            (
                '<li class="report-card">'
                f"<h2>{html.escape(report.title)}</h2>"
                f"<p><code>{html.escape(report.export_id)}</code></p>"
                f"<p>結果 <code>{html.escape(report.result_id)}</code></p>"
                f'<p><time datetime="{html.escape(report.generated_at)}">'
                f"{html.escape(report.generated_at or '時間未記錄')}</time></p>"
                f'<a href="{html.escape(report.href, quote=True)}">'
                f"{'開啟 HTML 報告' if report.href.endswith('.html') else '檢視 JSON 報告'}"
                "</a></li>"
            )
            for report in reports
        )
    else:
        cards = '<li class="empty">目前沒有已公開報告。</li>'
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drawdown Ledger｜公開報告</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; background: #eef2f6; color: #10243e; }}
    main {{ width: min(960px, calc(100% - 32px)); margin: 48px auto; }}
    header, li {{ border: 1px solid #b8c5d4; background: #fff; padding: 24px; }}
    ul {{ display: grid; gap: 16px; padding: 0; list-style: none; }}
    h1, h2 {{ margin-top: 0; }}
    a {{ color: #174fca; font-weight: 700; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main>
    <header>
      <p>Drawdown Ledger</p>
      <h1>已通過隱私檢查的公開報告</h1>
      <p>這些內容是固定日期的歷史研究，不是即時行情或個人化投資建議。</p>
    </header>
    <ul>
      {cards}
    </ul>
  </main>
</body>
</html>
"""


def build_publication_index(
    collection: Path,
    output: Path,
) -> tuple[PublishedReport, ...]:
    reports = validate_published_collection(collection)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_render_index(reports))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return reports


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate public report bundles and optionally build an index."
    )
    parser.add_argument("collection", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        reports = (
            build_publication_index(arguments.collection, arguments.output)
            if arguments.output is not None
            else validate_published_collection(arguments.collection)
        )
    except PublicationCollectionError as error:
        print(str(error))
        return 2
    print(
        json.dumps(
            {
                "allowed": True,
                "report_count": len(reports),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
