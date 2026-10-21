"""Export the API contracts as one JSON Schema file.

Usage: python -m app.export_schema <out_path>

The web app turns the output into TypeScript (`npm run types`). Serialization mode is used so
fields with defaults are required in TypeScript (the API always sends them).
"""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.models import (
    Attempt,
    AttemptConfig,
    AttemptStartedEvent,
    BlockSignal,
    BudgetEvent,
    CheckResult,
    Diagnosis,
    DiagnosisEvent,
    Evidence,
    ExpectedCheck,
    FetchExtraction,
    Health,
    LiveViewEvent,
    LlmDiagnosis,
    Patch,
    Run,
    RunCreated,
    RungChangeEvent,
    RunRequest,
    SiteInfo,
    Stats,
    StatsRow,
    TraceEvent,
    TraceUiEvent,
    UiEvent,
    VerdictEvent,
    VerifyEvent,
    VerifyResult,
)

EXPORTED: list[type[BaseModel]] = [
    RunRequest,
    ExpectedCheck,
    AttemptConfig,
    TraceEvent,
    CheckResult,
    BlockSignal,
    VerifyResult,
    Evidence,
    Patch,
    Diagnosis,
    Attempt,
    Run,
    UiEvent,
    AttemptStartedEvent,
    TraceUiEvent,
    LiveViewEvent,
    VerifyEvent,
    DiagnosisEvent,
    RungChangeEvent,
    BudgetEvent,
    VerdictEvent,
    FetchExtraction,
    LlmDiagnosis,
    SiteInfo,
    StatsRow,
    Stats,
    RunCreated,
    Health,
]

# Sub-schema containers to descend into. "properties" maps field names to schemas, so its own
# keys are never treated as schema keywords.
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_VALUES = ("items", "additionalProperties", "not")


def _strip_nested_titles(node: Any) -> None:
    """Drop `title` from nested schemas so json2ts doesn't emit an alias per field."""
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    for sub in (node.get("properties") or {}).values():
        _strip_nested_titles(sub)
    for key in _SCHEMA_LISTS:
        for sub in node.get(key) or []:
            _strip_nested_titles(sub)
    for key in _SCHEMA_VALUES:
        _strip_nested_titles(node.get(key))


def build_schema() -> dict[str, Any]:
    _, top = models_json_schema(
        [(model, "serialization") for model in EXPORTED],
        ref_template="#/definitions/{model}",
    )
    definitions: dict[str, Any] = top.get("$defs", {})
    for name, definition in definitions.items():
        for sub in (definition.get("properties") or {}).values():
            _strip_nested_titles(sub)
        for key in _SCHEMA_LISTS:
            for sub in definition.get(key) or []:
                _strip_nested_titles(sub)
        definition["title"] = name
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Contracts",
        "type": "object",
        "properties": {name: {"$ref": f"#/definitions/{name}"} for name in sorted(definitions)},
        "additionalProperties": False,
        "definitions": definitions,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.export_schema <out_path>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
