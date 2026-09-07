from types import SimpleNamespace

import pytest

from app.main import api
from app.routers.reports import unlocked_new_apps_alert
from app.services import apps as A


def app(package, label, is_system=False, version_name=None):
    return SimpleNamespace(
        package=package, label=label, is_system=is_system, version_name=version_name
    )


def test_pemasangan_baru_terbaca_sebagai_penambahan():
    dipasang, dicopot = A.compare({"a": "Alfa"}, {"a": "Alfa", "b": "Beta"})
    assert [x.package for x in dipasang] == ["b"]
    assert dicopot == []


def test_pencopotan_terbaca_dari_paket_yang_hilang():
    dipasang, dicopot = A.compare({"a": "Alfa", "b": "Beta"}, {"a": "Alfa"})
    assert dipasang == []
    assert [x.package for x in dicopot] == ["b"]


def test_nama_pencopotan_diambil_dari_catatan_lama():
    _, dicopot = A.compare({"com.game": "Free Fire"}, {})
    assert dicopot[0].label == "Free Fire", (
        "paket yang sudah hilang tidak ada di kiriman terbaru, jadi namanya "
        "harus diambil dari baris yang tersimpan supaya laporan tetap terbaca orang"
    )


def test_kiriman_yang_sama_persis_tidak_menghasilkan_perubahan():
    dipasang, dicopot = A.compare({"a": "Alfa", "b": "Beta"}, {"b": "Beta", "a": "Alfa"})
    assert not dipasang and not dicopot


def test_ganti_nama_aplikasi_bukan_pemasangan_baru():
    dipasang, dicopot = A.compare({"a": "Alfa"}, {"a": "Alfa Pro"})
    assert not dipasang and not dicopot, (
        "identitas aplikasi adalah nama paketnya; label bisa berubah saat aplikasi "
        "diperbarui atau bahasa ponsel diganti"
    )


def test_paket_kembar_diringkas_agar_upsert_tidak_bentrok():
    hasil = A.deduplicate([app("a", "Lama"), app("b", "Beta"), app("a", "Baru")])
    assert len(hasil) == 2
    assert {x.package: x.label for x in hasil}["a"] == "Baru", (
        "ON CONFLICT DO UPDATE menolak menyentuh baris yang sama dua kali dalam "
        "satu perintah, jadi kiriman kembar harus diringkas lebih dulu"
    )


def test_peringatan_hanya_menyebut_aplikasi_yang_belum_dikunci():
    baru = [
        {"package": "com.ff", "label": "Free Fire"},
        {"package": "com.ml", "label": "Mobile Legends"},
    ]
    assert unlocked_new_apps_alert(baru, {"com.ml"}) == (
        "1 aplikasi baru terpasang dan belum dikunci: Free Fire."
    )


def test_peringatan_meringkas_daftar_yang_panjang():
    baru = [{"package": f"p{i}", "label": f"Aplikasi {i}"} for i in range(5)]
    pesan = unlocked_new_apps_alert(baru, set())
    assert pesan.startswith("5 aplikasi baru terpasang dan belum dikunci: ")
    assert pesan.endswith("dan 2 lainnya.")


def test_tanpa_aplikasi_baru_tidak_ada_peringatan():
    assert unlocked_new_apps_alert([], set()) is None
    assert unlocked_new_apps_alert([{"package": "a", "label": "Alfa"}], {"a"}) is None


@pytest.fixture(scope="module")
def spec():
    return api.openapi()


def test_daftar_aplikasi_menyebut_status_kunci(spec):
    props = spec["components"]["schemas"]["InstalledAppOut"]["properties"]
    assert "locked" in props, (
        "layar pengaturan aturan memakai daftar ini sebagai pemilih aplikasi, jadi "
        "tiap baris harus tahu dirinya sudah dikunci atau belum"
    )
    assert "is_new" in props


def test_pengiriman_daftar_aplikasi_membutuhkan_otorisasi(spec):
    op = spec["paths"]["/devices/apps"]["put"]
    assert any(p.get("name", "").lower() == "authorization" for p in op["parameters"])


def test_kiriman_kosong_ditolak_agar_daftar_tidak_terhapus(spec):
    field = spec["components"]["schemas"]["AppInventoryIn"]["properties"]["apps"]
    assert field["minItems"] == 1, (
        "kiriman kosong dari klien yang bermasalah akan terbaca sebagai semua "
        "aplikasi dicopot dan mengosongkan daftar yang dilihat orang tua"
    )
    assert field["maxItems"] == 1000
