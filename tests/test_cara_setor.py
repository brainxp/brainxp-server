import pytest

from app.errors import Invalid
from app.services.documents import classify, method_for

FOTO = ["image/jpeg", "image/png", "image/webp"]
DOKUMEN = [
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.presentation",
]


@pytest.mark.parametrize("media_type", FOTO)
def test_gambar_selalu_dihitung_sebagai_foto(media_type):
    assert method_for(classify(media_type)) == "photo", (
        "aturan orang tua yang melarang foto tidak boleh bisa dilewati hanya dengan "
        "memilih gambar lewat tombol kirim dokumen"
    )


@pytest.mark.parametrize("media_type", DOKUMEN)
def test_berkas_selain_gambar_dihitung_sebagai_dokumen(media_type):
    assert method_for(classify(media_type)) == "document"


def test_jenis_asing_ditolak_sebelum_sempat_dinilai():
    with pytest.raises(Invalid):
        classify("application/x-msdownload")
