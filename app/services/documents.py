from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
from pathlib import Path

from app.errors import Invalid, TooLarge

PASSTHROUGH = {
    "application/pdf": "pdf",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/heic": "image",
    "image/heif": "image",
    "text/plain": "text",
    "text/markdown": "text",
}

CONVERTIBLE = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "pptx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.presentation": "odp",
}

UNSUPPORTED_IMAGE = {"image/heic", "image/heif"}


MAX_PAGES = 600


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify(media_type: str) -> str:
    mt = (media_type or "").split(";")[0].strip().lower()
    if mt in PASSTHROUGH:
        return PASSTHROUGH[mt]
    if mt in CONVERTIBLE:
        return CONVERTIBLE[mt]
    raise Invalid(
        f"Jenis berkas {mt or 'tidak dikenal'} belum didukung. "
        "Kirim PDF, DOCX, PPTX, ODT, ODP, TXT, atau foto JPG/PNG.",
        code="unsupported_media",
    )


def guard_size(data: bytes, limit: int) -> None:
    if len(data) > limit:
        raise TooLarge(f"Berkas {len(data) // 1_048_576} MB melampaui batas {limit // 1_048_576} MB.")


def pdf_page_count(data: bytes) -> int | None:
    if not data.startswith(b"%PDF"):
        return None
    n = data.count(b"/Type/Page") + data.count(b"/Type /Page")
    return n or None


async def to_attachment_bytes(*, data: bytes, media_type: str) -> tuple[bytes, str]:
    mt = (media_type or "").split(";")[0].strip().lower()
    kind = classify(mt)

    if mt in UNSUPPORTED_IMAGE:
        raise Invalid(
            "Format HEIC belum didukung. Aplikasi Android mengubah foto ke JPEG "
            "sebelum mengunggah.",
            code="unsupported_media",
        )

    if kind in ("pdf", "image", "text"):
        return data, mt

    return await _office_to_pdf(data, kind), "application/pdf"


async def _office_to_pdf(data: bytes, ext: str) -> bytes:
    if not shutil.which("soffice"):
        raise Invalid(
            "Konversi dokumen Office tidak tersedia di proses ini. "
            "Pekerjaan ini seharusnya dijalankan oleh worker.",
            code="converter_unavailable",
        )

    with tempfile.TemporaryDirectory(prefix="brainxp-") as tmp:
        src = Path(tmp) / f"masuk.{ext}"
        src.write_bytes(data)
        proc = await asyncio.create_subprocess_exec(
            "soffice", "--headless", "--norestore", "--convert-to", "pdf",
            "--outdir", tmp, str(src),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
            detail = (err or b"").decode("utf-8", "replace").strip()[-200:]
        except TimeoutError:
            proc.kill()
            raise Invalid("Konversi dokumen melewati batas waktu.", code="convert_timeout") from None

        out = Path(tmp) / "masuk.pdf"
        if proc.returncode != 0 or not out.exists():
            raise Invalid(
                "Dokumen tidak dapat dibaca. Coba simpan ulang sebagai PDF."
                + (f" ({detail})" if detail else ""),
                code="convert_failed",
            )
        return out.read_bytes()
