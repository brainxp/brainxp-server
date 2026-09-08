from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import api

SPEC = ROOT / "openapi.json"
DOC = ROOT / "API.md"

PUBLIC = {
    ("post", "/auth/register"), ("post", "/auth/login"), ("post", "/auth/refresh"),
    ("post", "/devices/pair"), ("post", "/devices/check-binding"), ("get", "/health"),
}

TAG_TITLE = {
    "auth": "Autentikasi",
    "family": "Keluarga, subjek, dan perangkat",
    "policy": "Aturan",
    "apps": "Aplikasi terpasang di perangkat",
    "materials": "Materi",
    "quiz": "Kuis dan penilaian",
    "ledger": "Saldo dan ekonomi waktu",
    "reports": "Laporan dan kemajuan",
    "guardian": "Peringatan pengawas",
    "ops": "Operasional",
}

TAG_ORDER = ["auth", "family", "policy", "apps", "materials", "quiz", "ledger",
             "reports", "guardian", "ops"]


def render(spec: dict) -> str:
    def ref_name(node: dict | None) -> str:
        if not node:
            return ""
        ref = node.get("$ref") or node.get("items", {}).get("$ref", "")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            return f"`{name}[]`" if "items" in node else f"`{name}`"
        return ""

    def body_of(op: dict) -> str:
        content = op.get("requestBody", {}).get("content", {})
        if "multipart/form-data" in content:
            return "berkas (multipart)"
        schema = content.get("application/json", {}).get("schema")
        return ref_name(schema) or "—"

    def result_of(op: dict) -> str:
        for code in ("200", "201", "202", "204"):
            r = op.get("responses", {}).get(code)
            if not r:
                continue
            schema = r.get("content", {}).get("application/json", {}).get("schema")
            return f"{code} {ref_name(schema)}".strip()
        return "—"

    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in spec["paths"].items():
        for verb, op in ops.items():
            tag = (op.get("tags") or ["ops"])[0]
            by_tag.setdefault(tag, []).append((verb, path, op))

    out = [
        "# BrainXP — Spesifikasi API",
        "",
        f"Versi {spec['info']['version']}. "
        f"{sum(len(v) for v in by_tag.values())} operasi pada {len(spec['paths'])} path.",
        "",
        "Berkas ini dibangkitkan dari kode oleh `scripts/gen_openapi.py`. "
        "Jangan disunting langsung — ubah routernya, lalu jalankan skripnya.",
        "Sumber kebenarannya adalah `openapi.json`; berkas ini hanya versi yang enak dibaca.",
        "",
        "Seluruh operasi memakai JSON kecuali unggah materi yang memakai multipart. "
        "Otorisasi memakai header `Authorization: Bearer <access_token>`.",
        "",
    ]

    for tag in TAG_ORDER + sorted(set(by_tag) - set(TAG_ORDER)):
        rows = by_tag.get(tag)
        if not rows:
            continue
        out.append(f"## {TAG_TITLE.get(tag, tag)}")
        out.append("")
        out.append("| Operasi | Auth | Kirim | Terima |")
        out.append("|---|---|---|---|")
        for verb, path, op in sorted(rows, key=lambda r: (r[1], r[0])):
            auth = "—" if (verb, path) in PUBLIC else "Bearer"
            out.append(
                f"| `{verb.upper()} {path}` | {auth} | {body_of(op)} | {result_of(op)} |"
            )
        out.append("")

    out.append("## Skema")
    out.append("")
    for name, schema in sorted(spec.get("components", {}).get("schemas", {}).items()):
        props = schema.get("properties", {})
        if not props:
            continue
        required = set(schema.get("required", []))
        fields = ", ".join(
            f"`{k}`" + ("" if k in required else "?") for k in sorted(props)
        )
        out.append(f"- **{name}** — {fields}")
    out.append("")

    out.append("## Yang tidak pernah dikirim ke klien")
    out.append("")
    out.append(
        "`correct_index`, `rubric`, dan `reference_answer` tidak muncul pada skema mana pun "
        "selain `AnswerFeedbackOut`, yang hanya dikembalikan setelah sebuah soal dijawab. "
        "Aturan ini dijaga `tests/test_api_contract.py`."
    )
    out.append("")
    return "\n".join(out)


def build() -> tuple[str, str]:
    api.openapi_schema = None
    spec = api.openapi()
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n", render(spec)


def main() -> int:
    spec_text, doc_text = build()
    if "--check" in sys.argv:
        if SPEC.exists() and SPEC.read_text() == spec_text:
            return 0
        print(f"API spec is stale: {SPEC.name}")
        print("run: python scripts/gen_openapi.py")
        return 1
    SPEC.write_text(spec_text)
    DOC.write_text(doc_text)
    print(f"written: {SPEC.name}, {DOC.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
