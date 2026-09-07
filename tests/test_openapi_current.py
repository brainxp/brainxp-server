import json

from scripts.gen_openapi import DOC, SPEC, build

CURRENT_SPEC, CURRENT_DOC = build()
COMMAND = "python scripts/gen_openapi.py"


def test_openapi_json_exists():
    assert SPEC.exists(), f"openapi.json has not been generated. Run: {COMMAND}"


def test_api_md_exists():
    assert DOC.exists(), f"API.md has not been generated. Run: {COMMAND}"


def test_openapi_json_is_not_stale():
    assert SPEC.read_text() == CURRENT_SPEC, (
        f"openapi.json does not match the code. Run: {COMMAND}"
    )


def test_api_md_is_not_stale():
    assert DOC.read_text() == CURRENT_DOC, f"API.md does not match the code. Run: {COMMAND}"


def test_the_stored_spec_parses():
    spec = json.loads(SPEC.read_text())
    assert spec["info"]["title"] == "BrainXP"
    assert len(spec["paths"]) >= 30


def test_every_operation_has_a_success_response():
    spec = json.loads(SPEC.read_text())
    without = [
        f"{verb.upper()} {path}"
        for path, ops in spec["paths"].items()
        for verb, op in ops.items()
        if not any(c in op.get("responses", {}) for c in ("200", "201", "202", "204"))
    ]
    assert not without, f"operations without a success response: {without}"


def test_every_operation_has_a_tag():
    spec = json.loads(SPEC.read_text())
    without = [
        f"{verb.upper()} {path}"
        for path, ops in spec["paths"].items()
        for verb, op in ops.items()
        if not op.get("tags")
    ]
    assert not without, f"operations without a tag, they will not reach API.md: {without}"
