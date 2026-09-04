from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import rules as R

JKT = ZoneInfo("Asia/Jakarta")


@pytest.mark.parametrize(
    "declared,assessed,expected",
    [
        ("smp", "smp", 1.0),
        ("smp", "sma", 1.0),
        ("sma", "smp", 0.6),
        ("sma", "sd", 0.0),
        ("kuliah", "sd", 0.0),
    ],
)
def test_level_factor(declared, assessed, expected):
    assert R.level_factor(declared, assessed) == expected


def test_gate_menolak_materi_dua_tingkat_di_bawah():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="sd",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert not out.accepted
    assert out.reject_reason == R.RejectReason.LEVEL_TOO_LOW


def test_gate_menerima_smp_dengan_materi_sd_sebagai_satu_tingkat():
    out = R.evaluate_gate(
        declared_level="smp", assessed_level="sd",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert out.accepted
    assert out.level_factor == 0.6


def test_gate_menerima_satu_tingkat_di_bawah_dengan_reward_lebih_kecil():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="smp",
        concept_density=0.5, is_study_material=True, times_seen=0,
    )
    assert out.accepted
    assert out.level_factor == 0.6


def test_gate_menolak_materi_terlalu_tipis():
    out = R.evaluate_gate(
        declared_level="smp", assessed_level="smp",
        concept_density=0.05, is_study_material=True, times_seen=0,
    )
    assert not out.accepted
    assert out.reject_reason == R.RejectReason.TOO_THIN


def test_peluruhan_kebaruan():
    assert R.novelty_factor(0) == 1.0
    assert R.novelty_factor(1) == 0.6
    assert R.novelty_factor(5) == 0.3


def test_celah_yang_dicoba_bersamaan_saling_memperkecil():
    out = R.evaluate_gate(
        declared_level="sma", assessed_level="smp",
        concept_density=0.4, is_study_material=True, times_seen=2,
    )
    assert out.combined == pytest.approx(0.6 * 0.3)


def test_ambang_bloom_sma_butuh_mayoritas_soal_analitis():
    hafalan = ["remember"] * 10
    campur = ["apply"] * 6 + ["remember"] * 4
    assert not R.bloom_floor_met(hafalan, "sma")
    assert R.bloom_floor_met(campur, "sma")
    assert R.bloom_floor_met(hafalan, "sd")


def test_reward_pilihan_ganda_sesuai_kesulitan():
    kw = {"base_seconds": 120, "qtype": "mcq", "level_factor_": 1.0,
          "novelty_factor_": 1.0, "correct": True}
    assert R.question_reward(difficulty="mudah", **kw) == pytest.approx(72.0)
    assert R.question_reward(difficulty="sedang", **kw) == pytest.approx(120.0)
    assert R.question_reward(difficulty="sulit", **kw) == pytest.approx(192.0)


def test_jawaban_salah_tidak_berbuah():
    assert R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="mcq",
        level_factor_=1.0, novelty_factor_=1.0, correct=False,
    ) == 0.0


def test_esai_bernilai_lebih_dan_proporsional_terhadap_skor():
    r = R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="essay",
        level_factor_=1.0, novelty_factor_=1.0, score=82,
    )
    assert r == pytest.approx(120 * 1.6 * 1.8 * 0.82)


def test_esai_di_bawah_ambang_tidak_berbuah():
    assert R.question_reward(
        base_seconds=120, difficulty="sulit", qtype="essay",
        level_factor_=1.0, novelty_factor_=1.0, score=59,
    ) == 0.0


def test_sesi_penuh_cocok_dengan_hitungan_manual():
    base = 120
    total = sum(
        R.question_reward(base_seconds=base, difficulty=d, qtype="mcq",
                          level_factor_=1.0, novelty_factor_=1.0, correct=True)
        for d in ["sedang", "mudah", "sedang", "sulit", "sedang", "mudah", "sulit", "sedang"]
    )
    total += R.question_reward(base_seconds=base, difficulty="sulit", qtype="essay",
                               level_factor_=1.0, novelty_factor_=1.0, score=82)
    assert total == pytest.approx(1008 + 283.392)


def test_batas_atas_sesi():
    mx = R.max_possible_reward(base_seconds=120, questions=10, essay_ratio=0.2)
    assert mx == pytest.approx(8 * 192 + 2 * 192 * 1.8)


def test_reward_masuk_penuh_saat_masih_ada_ruang():
    s = R.settle(1800, balance=0, ceiling=10800)
    assert s.to_balance == 1800
    assert s.overflow_points == 0


def test_kelebihan_di_atas_plafon_jadi_poin_bukan_hangus():
    s = R.settle(1800, balance=10500, ceiling=10800)
    assert s.to_balance == 300
    assert s.overflow_points == 25


def test_saldo_penuh_seluruh_reward_jadi_poin():
    s = R.settle(600, balance=10800, ceiling=10800)
    assert s.to_balance == 0
    assert s.overflow_points == 10


def test_pukul_dua_pagi_masih_terhitung_hari_sebelumnya():
    malam = datetime(2026, 9, 3, 23, 40, tzinfo=JKT)
    dini = datetime(2026, 9, 4, 2, 10, tzinfo=JKT)
    assert R.day_key(malam, reset_hour=5) == R.day_key(dini, reset_hour=5)
    assert R.day_key(dini, reset_hour=5) == date(2026, 9, 3)


def test_tengah_malam_memisahkan_hari_bila_reset_nol():
    malam = datetime(2026, 9, 3, 23, 40, tzinfo=JKT)
    dini = datetime(2026, 9, 4, 0, 10, tzinfo=JKT)
    assert R.day_key(malam, reset_hour=0) != R.day_key(dini, reset_hour=0)


def test_sisa_waktu_menuju_pergantian_hari():
    saat = datetime(2026, 9, 3, 22, 0, tzinfo=JKT)
    assert R.seconds_until_reset(saat, reset_hour=5) == 7 * 3600


def test_kuota_harian_membatasi_meski_saldo_besar():
    assert R.playable_seconds(balance=10800, daily_cap=3600, spent_today=3000) == 600


def test_saldo_kecil_membatasi_meski_kuota_longgar():
    assert R.playable_seconds(balance=300, daily_cap=3600, spent_today=0) == 300


def test_dua_alasan_terkunci_dibedakan():
    assert R.block_reason(balance=0, daily_cap=3600, spent_today=0) == R.BlockReason.NO_BALANCE
    assert R.block_reason(balance=4200, daily_cap=3600, spent_today=3600) == R.BlockReason.DAILY_CAP
    assert R.block_reason(balance=4200, daily_cap=3600, spent_today=600) == R.BlockReason.NONE


def test_streak_bertambah_pada_hari_berurutan():
    s = R.StreakState(3, 5, 0, date(2026, 9, 2))
    s2 = R.advance_streak(s, date(2026, 9, 3))
    assert s2.current == 4


def test_sesi_kedua_pada_hari_yang_sama_tidak_menambah_streak():
    s = R.StreakState(3, 5, 0, date(2026, 9, 3))
    assert R.advance_streak(s, date(2026, 9, 3)) == s


def test_jatah_bolong_menyelamatkan_satu_hari_terlewat():
    s = R.StreakState(9, 9, 1, date(2026, 9, 1))
    s2 = R.advance_streak(s, date(2026, 9, 3))
    assert s2.current == 10
    assert s2.freeze_tokens == 0


def test_tanpa_jatah_bolong_streak_putus():
    s = R.StreakState(9, 9, 0, date(2026, 9, 1))
    s2 = R.advance_streak(s, date(2026, 9, 3))
    assert s2.current == 1
    assert s2.longest == 9


def test_jatah_bolong_diperoleh_tiap_tujuh_hari_dan_maksimal_dua():
    s = R.StreakState(6, 6, 0, date(2026, 9, 2))
    s = R.advance_streak(s, date(2026, 9, 3))
    assert (s.current, s.freeze_tokens) == (7, 1)
    for i in range(4, 11):
        s = R.advance_streak(s, date(2026, 9, i))
    assert s.current == 14
    assert s.freeze_tokens == 2


def test_pembagian_soal_mengikuti_porsi_esai():
    assert R.session_mix(10, 0.2) == (8, 2)
    assert R.session_mix(10, 0.0) == (10, 0)
    assert R.session_mix(10, 1.0) == (0, 10)
    assert R.session_mix(5, 0.4) == (3, 2)


def test_batch_prioritas_tidak_melebihi_jumlah_soal():
    assert R.priority_batch_size(10) == 3
    assert R.priority_batch_size(2) == 2


def test_alasan_pemblokiran_punya_nilai_khusus_untuk_penjaga_basi():
    assert R.BlockReason.GUARDIAN_STALE == "guardian_stale"
    assert R.BlockReason.GUARDIAN_STALE not in (
        R.BlockReason.NO_BALANCE, R.BlockReason.DAILY_CAP, R.BlockReason.NONE
    )


def test_saldo_utuh_tidak_pernah_dilaporkan_kehabisan_saldo():
    assert R.block_reason(balance=1740, daily_cap=3600, spent_today=60) == R.BlockReason.NONE


def test_worker_menunggu_baris_materi_cukup_lama():
    from app.services import generation as G

    assert G.VISIBILITY_TRIES * G.VISIBILITY_PAUSE >= 3.0, (
        "unggahan besar butuh beberapa detik untuk commit; jendela tunggunya "
        "harus lebih panjang dari itu supaya worker tidak menyerah lebih dulu"
    )
