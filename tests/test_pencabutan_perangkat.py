import inspect

from fastapi.dependencies.utils import get_dependant

from app import deps
from app.db import conn
from app.security import now

TERIKAT = {"unbound_at": None, "deleted_at": None}


def test_perangkat_terikat_diterima():
    assert deps.revoked_reason(TERIKAT) is None


def test_perangkat_yang_sudah_dikeluarkan_ditolak():
    assert deps.revoked_reason({"unbound_at": now(), "deleted_at": None}) is not None, (
        "mencabut refresh token saja tidak cukup: access token yang sudah terbit "
        "masih berlaku sampai 15 menit, dan selama itu perangkat lama bisa "
        "memotong saldo serta menarik bank soal luring"
    )


def test_profil_yang_sudah_dihapus_ditolak():
    assert deps.revoked_reason({"unbound_at": None, "deleted_at": now()}) is not None


def test_perangkat_yang_hilang_dari_basis_data_ditolak():
    assert deps.revoked_reason(None) is not None


def test_alasan_penolakan_menyebut_langkah_berikutnya():
    pesan = deps.revoked_reason({"unbound_at": now(), "deleted_at": None})
    assert "Pasangkan ulang" in pesan, (
        "klien memakai pesan ini untuk memutuskan menampilkan layar pemasangan ulang"
    )


def test_identitas_pemanggil_diperiksa_ke_basis_data():
    dependant = get_dependant(path="/x", call=deps.caller)
    assert any(sub.call is conn for sub in dependant.dependencies), (
        "caller harus punya koneksi basis data; tanpa itu tidak ada yang "
        "memeriksa perangkatnya masih terikat"
    )


def test_token_perangkat_selalu_lewat_pemeriksaan_ikatan():
    source = inspect.getsource(deps.caller)
    assert "require_bound_device" in source
    assert "me.device_id" in source, (
        "token orang tua tidak membawa device_id, jadi pemeriksaannya harus "
        "bersyarat supaya tidak menambah query untuk mereka"
    )


def test_pemeriksaan_ikatan_membaca_dua_tabel_sekaligus():
    source = inspect.getsource(deps.require_bound_device)
    assert "unbound_at" in source and "deleted_at" in source, (
        "perangkat dikeluarkan dan profil dihapus adalah dua kejadian berbeda; "
        "keduanya harus tertutup dalam satu query"
    )
