"""Generate deterministic TypeScript types from the FastAPI OpenAPI document.

This deliberately has no Node code-generation dependency. The backend's own
Pydantic/OpenAPI document is the single contract source, and ``--check`` makes
contract drift fail CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

WEB_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = WEB_ROOT.parents[1]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
DEFAULT_OUTPUT = WEB_ROOT / "src" / "lib" / "openapi.generated.ts"

sys.path.insert(0, str(API_SOURCE))

from drawdown_lab.api.app import Settings, create_app  # noqa: E402, I001


JsonObject = Mapping[str, Any]


def literal(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False)
    return "unknown"


def indent(value: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else line for line in value.splitlines())


def reference_type(reference: str) -> str:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        return "unknown"
    name = reference.removeprefix(prefix)
    return f'components["schemas"][{json.dumps(name)}]'


def union(types: Iterable[str]) -> str:
    unique = tuple(dict.fromkeys(types))
    return " | ".join(unique) if unique else "never"


def schema_type(schema: JsonObject) -> str:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return reference_type(reference)

    if "const" in schema:
        return literal(schema["const"])

    enum = schema.get("enum")
    if isinstance(enum, list):
        return union(literal(item) for item in enum)

    for key, separator in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        variants = schema.get(key)
        if isinstance(variants, list):
            rendered = [schema_type(item) for item in variants if isinstance(item, dict)]
            return separator.join(dict.fromkeys(rendered)) if rendered else "unknown"

    schema_kind = schema.get("type")
    if isinstance(schema_kind, list):
        return union(
            schema_type({**schema, "type": item})
            for item in schema_kind
            if isinstance(item, str)
        )
    if schema_kind == "string":
        return "string"
    if schema_kind in {"integer", "number"}:
        return "number"
    if schema_kind == "boolean":
        return "boolean"
    if schema_kind == "null":
        return "null"
    if schema_kind == "array":
        items = schema.get("items")
        item_type = schema_type(items) if isinstance(items, dict) else "unknown"
        return f"Array<{item_type}>"
    if schema_kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = frozenset(schema.get("required", []))
        fields: list[str] = []
        if isinstance(properties, dict):
            for name in sorted(properties):
                property_schema = properties[name]
                if not isinstance(property_schema, dict):
                    continue
                optional = "" if name in required else "?"
                fields.append(
                    f"{json.dumps(name, ensure_ascii=False)}{optional}: "
                    f"{schema_type(property_schema)};"
                )
        additional = schema.get("additionalProperties")
        if additional is True:
            fields.append("[key: string]: unknown;")
        elif isinstance(additional, dict):
            fields.append(f"[key: string]: {schema_type(additional)};")
        if not fields:
            return "Record<string, never>"
        return "{\n" + indent("\n".join(fields)) + "\n}"
    return "unknown"


def response_type(response: JsonObject) -> str:
    content = response.get("content")
    if not isinstance(content, dict):
        return "never"
    json_content = content.get("application/json")
    if not isinstance(json_content, dict):
        return "unknown"
    schema = json_content.get("schema")
    return schema_type(schema) if isinstance(schema, dict) else "unknown"


def request_type(operation: JsonObject) -> str:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return "never"
    return response_type(body)


def parameter_groups(
    path_parameters: object,
    operation_parameters: object,
) -> str:
    parameters: list[JsonObject] = []
    for source in (path_parameters, operation_parameters):
        if isinstance(source, list):
            parameters.extend(item for item in source if isinstance(item, dict))

    grouped: dict[str, list[str]] = {}
    for parameter in parameters:
        location = parameter.get("in")
        name = parameter.get("name")
        parameter_schema = parameter.get("schema")
        if (
            not isinstance(location, str)
            or not isinstance(name, str)
            or not isinstance(parameter_schema, dict)
        ):
            continue
        optional = "" if parameter.get("required") is True else "?"
        grouped.setdefault(location, []).append(
            f"{json.dumps(name, ensure_ascii=False)}{optional}: "
            f"{schema_type(parameter_schema)};"
        )

    if not grouped:
        return "Record<string, never>"
    locations = [
        f"{json.dumps(location)}: {{\n{indent(chr(10).join(sorted(fields)), 8)}\n    }};"
        for location, fields in sorted(grouped.items())
    ]
    return "{\n" + indent("\n".join(locations)) + "\n}"


def operation_type(path_item: JsonObject, operation: JsonObject) -> str:
    responses = operation.get("responses", {})
    rendered_responses: list[str] = []
    if isinstance(responses, dict):
        for status, response in sorted(responses.items()):
            if isinstance(response, dict):
                rendered_responses.append(
                    f"{json.dumps(str(status))}: {response_type(response)};"
                )
    response_block = (
        "{\n" + indent("\n".join(rendered_responses), 8) + "\n    }"
        if rendered_responses
        else "Record<string, never>"
    )
    parameter_block = parameter_groups(
        path_item.get("parameters"),
        operation.get("parameters"),
    )
    return (
        "{\n"
        f"    parameters: {parameter_block};\n"
        f"    requestBody: {request_type(operation)};\n"
        f"    responses: {response_block};\n"
        "}"
    )


def generate(openapi: JsonObject) -> str:
    components = openapi.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    schema_lines: list[str] = []
    if isinstance(schemas, dict):
        for name in sorted(schemas):
            schema = schemas[name]
            if isinstance(schema, dict):
                schema_lines.append(
                    f"{json.dumps(name, ensure_ascii=False)}: {schema_type(schema)};"
                )

    paths = openapi.get("paths", {})
    path_lines: list[str] = []
    if isinstance(paths, dict):
        for path in sorted(paths):
            path_item = paths[path]
            if not isinstance(path_item, dict):
                continue
            methods: list[str] = []
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if isinstance(operation, dict):
                    methods.append(
                        f"{method}: {operation_type(path_item, operation)};"
                    )
            if methods:
                path_lines.append(
                    f"{json.dumps(path, ensure_ascii=False)}: "
                    "{\n"
                    f"{indent(chr(10).join(methods), 8)}\n"
                    "    };"
                )

    return (
        "/**\n"
        " * AUTO-GENERATED from FastAPI app.openapi(). Do not edit by hand.\n"
        " * Run `python scripts/generate_openapi_types.py` after API changes.\n"
        " */\n\n"
        "export interface components {\n"
        '    "schemas": {\n'
        f"{indent(chr(10).join(schema_lines), 8)}\n"
        "    };\n"
        "}\n\n"
        "export interface paths {\n"
        f"{indent(chr(10).join(path_lines), 4)}\n"
        "}\n"
    )


def openapi_document() -> JsonObject:
    with tempfile.TemporaryDirectory(prefix="drawdown-openapi-") as temp_directory:
        settings = Settings(database_path=Path(temp_directory) / "contract.sqlite3")
        return create_app(settings).openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    expected = generate(openapi_document())
    output = arguments.output.resolve()
    if arguments.check:
        actual = output.read_text(encoding="utf-8") if output.exists() else ""
        if actual != expected:
            print(
                f"{output} is stale; regenerate it from the current FastAPI OpenAPI contract.",
                file=sys.stderr,
            )
            return 1
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
