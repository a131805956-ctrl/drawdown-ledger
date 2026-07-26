"""Canonical passive HTML rendering for report bundles."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


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


def canonical_report_html(report_seed: Mapping[str, object]) -> bytes:
    candidates = report_seed.get("candidates")
    recommendations = report_seed.get("recommendations")
    lineage = report_seed.get("lineage")
    result_id = report_seed.get("result_id")
    schema_version = report_seed.get("schema_version")
    stored_schema_version = report_seed.get("stored_schema_version")
    title = report_seed.get("title")
    disclaimer = report_seed.get("disclaimer")
    if (
        not isinstance(candidates, Sequence)
        or isinstance(candidates, (bytes, bytearray, str))
        or not isinstance(recommendations, Sequence)
        or isinstance(recommendations, (bytes, bytearray, str))
        or not isinstance(lineage, Mapping)
        or not isinstance(lineage.get("parameters"), Mapping)
        or not isinstance(result_id, str)
        or not isinstance(schema_version, str)
        or not isinstance(stored_schema_version, str)
        or not isinstance(title, str)
        or not isinstance(disclaimer, str)
    ):
        raise ValueError("Canonical report seed cannot render HTML")
    template = _template_environment().get_template("report.html.j2")
    rendered = template.render(
        disclaimer=disclaimer,
        candidates=candidates,
        lineage=lineage,
        parameters_json=json.dumps(
            lineage["parameters"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        report_json=json.dumps(
            report_seed,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        result_id=result_id,
        schema_version=schema_version,
        stored_schema_version=stored_schema_version,
        title=title,
        recommendations=recommendations,
    )
    return rendered.encode("utf-8")
