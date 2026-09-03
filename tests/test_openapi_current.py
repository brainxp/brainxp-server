import json

from scripts.gen_openapi import DOC, SPEC, build

CURRENT_SPEC, CURRENT_DOC = build()
PERINTAH = "python scripts/gen_openapi.py"


def test_openapi_json_ada():
    assert SPEC.exists(), f"openapi.json belum dibuat. Jalankan: {PERINTAH}"


def test_api_md_ada():
    assert DOC.exists(), f"API.md belum dibuat. Jalankan: {PERINTAH}"


def test_openapi_json_tidak_basi():
    assert SPEC.read_text() == CURRENT_SPEC, (
        f"openapi.json tidak cocok dengan kode. Jalankan: {PERINTAH}"
    )


def test_api_md_tidak_basi():
    assert DOC.read_text() == CURRENT_DOC, (
        f"API.md tidak cocok dengan kode. Jalankan: {PERINTAH}"
    )


def test_spesifikasi_tersimpan_bisa_diurai():
    spec = json.loads(SPEC.read_text())
    assert spec["info"]["title"] == "BrainXP"
    assert len(spec["paths"]) >= 30


def test_setiap_operasi_punya_respons_sukses():
    spec = json.loads(SPEC.read_text())
    tanpa = [
        f"{verb.upper()} {path}"
        for path, ops in spec["paths"].items()
        for verb, op in ops.items()
        if not any(c in op.get("responses", {}) for c in ("200", "201", "202", "204"))
    ]
    assert not tanpa, f"operasi tanpa respons sukses: {tanpa}"


def test_setiap_operasi_punya_tag():
    spec = json.loads(SPEC.read_text())
    tanpa = [
        f"{verb.upper()} {path}"
        for path, ops in spec["paths"].items()
        for verb, op in ops.items()
        if not op.get("tags")
    ]
    assert not tanpa, f"operasi tanpa tag, tidak akan muncul di API.md: {tanpa}"
