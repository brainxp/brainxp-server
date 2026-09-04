from app.routers.policies import _is_weakening

BASE = {
    "questions_per_session": 10,
    "base_reward_seconds": 120,
    "daily_caps": [3600, 3600, 3600, 3600, 3600, 3600, 3600],
    "daily_grants": [0, 0, 0, 0, 0, 0, 0],
    "idle_days_allowed": 2,
    "essay_ratio": 0.2,
    "locked_apps": ["ml", "tt"],
}


def test_menambah_kuota_harian_adalah_pelonggaran():
    assert _is_weakening(BASE, {"daily_caps": [3600, 3600, 3600, 3600, 3600, 7200, 7200]})


def test_mengecilkan_kuota_harian_adalah_pengetatan():
    assert not _is_weakening(BASE, {"daily_caps": [1800] * 7})


def test_menambah_jatah_libur_adalah_pelonggaran():
    assert _is_weakening(BASE, {"idle_days_allowed": 4})


def test_mengurangi_jatah_libur_adalah_pengetatan():
    assert not _is_weakening(BASE, {"idle_days_allowed": 0})


def test_menaikkan_reward_per_soal_adalah_pelonggaran():
    assert _is_weakening(BASE, {"base_reward_seconds": 300})


def test_menurunkan_reward_per_soal_adalah_pengetatan():
    assert not _is_weakening(BASE, {"base_reward_seconds": 60})


def test_mengurangi_jumlah_soal_adalah_pelonggaran():
    assert _is_weakening(BASE, {"questions_per_session": 5})


def test_menambah_jumlah_soal_adalah_pengetatan():
    assert not _is_weakening(BASE, {"questions_per_session": 20})


def test_melepas_aplikasi_dari_daftar_kunci_adalah_pelonggaran():
    assert _is_weakening(BASE, {"locked_apps": ["ml"]})


def test_menambah_aplikasi_ke_daftar_kunci_adalah_pengetatan():
    assert not _is_weakening(BASE, {"locked_apps": ["ml", "tt", "ig"]})


def test_menukar_aplikasi_tetap_terhitung_pelonggaran():
    assert _is_weakening(BASE, {"locked_apps": ["ml", "ig"]})


def test_mengurangi_porsi_esai_adalah_pelonggaran():
    assert _is_weakening(BASE, {"essay_ratio": 0.0})


def test_perubahan_kosong_bukan_pelonggaran():
    assert not _is_weakening(BASE, {})
    assert not _is_weakening(BASE, {"daily_cap_seconds": None})


def test_melonggarkan_satu_hari_saja_tetap_pelonggaran():
    naik_sabtu = [3600, 1800, 1800, 1800, 1800, 7200, 1800]
    assert _is_weakening(BASE, {"daily_caps": naik_sabtu}), (
        "menaikkan satu hari tetap pelonggaran walau hari lain diperketat"
    )


def test_menurunkan_semua_hari_adalah_pengetatan():
    assert not _is_weakening(BASE, {"daily_caps": [1800] * 7})


def test_menaikkan_saldo_harian_akhir_pekan_adalah_pelonggaran():
    assert _is_weakening(BASE, {"daily_grants": [0, 0, 0, 0, 0, 1800, 1800]})
