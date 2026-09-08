from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

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
MAX_PHOTOS = 20
PHOTO_LONG_EDGE = 1568
PHOTO_QUALITY = 88
PHOTO_DPI = 150.0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_digest(parts: list[bytes]) -> str:
    if len(parts) == 1:
        return sha256_bytes(parts[0])
    return sha256_bytes("\n".join(sha256_bytes(p) for p in parts).encode())


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


def method_for(kind: str) -> str:
    return "photo" if kind == "image" else "document"


def guard_supported_image(media_type: str) -> None:
    if (media_type or "").split(";")[0].strip().lower() in UNSUPPORTED_IMAGE:
        raise Invalid(
            "Format HEIC belum didukung. Aplikasi Android mengubah foto ke JPEG "
            "sebelum mengunggah.",
            code="unsupported_media",
        )


def batch_method(media_types: list[str]) -> str:
    if not media_types:
        raise Invalid("Tidak ada berkas yang dikirim.")
    if len(media_types) > MAX_PHOTOS:
        raise Invalid(
            f"Satu materi menampung paling banyak {MAX_PHOTOS} foto, "
            f"dikirim {len(media_types)}.",
            code="too_many_photos",
        )

    kinds = [classify(mt) for mt in media_types]
    if len(kinds) == 1:
        return method_for(kinds[0])

    if set(kinds) != {"image"}:
        raise Invalid(
            "Beberapa berkas sekaligus hanya berlaku untuk foto. Kirim dokumen satu per satu.",
            code="mixed_upload",
        )
    for mt in media_types:
        guard_supported_image(mt)
    return "photo"


def guard_size(size: int, limit: int) -> None:
    if size > limit:
        raise TooLarge(f"Berkas {size // 1_048_576} MB melampaui batas {limit // 1_048_576} MB.")


PDF_PAGE = re.compile(rb"/Type\s*/Page(?!\w)")


def pdf_page_count(data: bytes) -> int | None:
    if not data.startswith(b"%PDF"):
        return None
    return len(PDF_PAGE.findall(data)) or None


def _page(data: bytes) -> Image.Image:
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise Invalid(
            "Salah satu foto tidak dapat dibaca. Kirim ulang dalam format JPG, PNG, atau WEBP.",
            code="unreadable_photo",
        ) from exc

    if image.mode != "RGB":
        image = image.convert("RGB")

    longest = max(image.size)
    if longest > PHOTO_LONG_EDGE:
        scale = PHOTO_LONG_EDGE / longest
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def _pages_to_pdf(parts: list[bytes]) -> bytes:
    pages = [_page(p) for p in parts]
    out = io.BytesIO()
    pages[0].save(
        out, "PDF", save_all=True, append_images=pages[1:],
        quality=PHOTO_QUALITY, resolution=PHOTO_DPI,
    )
    return out.getvalue()


async def photos_to_pdf(parts: list[bytes]) -> bytes:
    return await asyncio.to_thread(_pages_to_pdf, parts)


async def to_attachment_bytes(*, data: bytes, media_type: str) -> tuple[bytes, str]:
    mt = (media_type or "").split(";")[0].strip().lower()
    kind = classify(mt)

    guard_supported_image(mt)

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
