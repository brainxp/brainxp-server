import pytest

from app.services import ratelimit as RL


@pytest.mark.parametrize(
    "count,expected",
    [(1, False), (10, False), (11, True), (500, True)],
)
def test_batas_terlampaui_setelah_kuota_habis(count, expected):
    assert RL.exceeded(count, RL.PAIR_PER_IP) is expected


def test_kuota_global_lebih_longgar_dari_per_ip():
    assert RL.PAIR_GLOBAL.limit > RL.PAIR_PER_IP.limit


def test_kuota_global_menutup_penyapuan_ruang_kode():
    """
    Kode enam angka punya 10^6 kemungkinan dan hanya berlaku 10 menit.
    Batas global harus jauh lebih kecil daripada ruang itu agar penyapuan
    terdistribusi tetap tidak mungkin dalam satu masa berlaku.
    """
    assert RL.PAIR_GLOBAL.seconds <= 600
    assert RL.PAIR_GLOBAL.limit / 1_000_000 < 0.001


def test_ip_diambil_dari_x_real_ip_lebih_dulu():
    headers = {"x-real-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4, 5.6.7.8"}
    assert RL.client_ip(headers, "172.18.0.1") == "203.0.113.9"


def test_ip_memakai_entri_terakhir_x_forwarded_for():
    """
    nginx menambahkan alamat asli di akhir rantai, sehingga entri terakhir
    yang bisa dipercaya. Entri awal dapat dipalsukan penyerang.
    """
    headers = {"x-forwarded-for": "9.9.9.9, 203.0.113.9"}
    assert RL.client_ip(headers, "172.18.0.1") == "203.0.113.9"


def test_ip_jatuh_ke_alamat_koneksi_bila_tanpa_header():
    assert RL.client_ip({}, "198.51.100.7") == "198.51.100.7"
    assert RL.client_ip({}, None) == "unknown"
