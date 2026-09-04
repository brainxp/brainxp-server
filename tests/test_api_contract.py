import pytest

from app.main import api

SECRETS = {"correct_index", "rubric", "reference_answer"}

ALLOWED: set[str] = set()


@pytest.fixture(scope="module")
def spec():
    return api.openapi()


def test_skema_soal_publik_tidak_punya_tempat_untuk_kunci_jawaban(spec):
    props = set(spec["components"]["schemas"]["QuestionPublic"]["properties"])
    assert not (props & SECRETS), f"QuestionPublic membocorkan {props & SECRETS}"


def test_bank_luring_hanya_mengirim_hmac(spec):
    props = set(spec["components"]["schemas"]["OfflineQuestionOut"]["properties"])
    assert not (props & SECRETS)
    assert "answer_hmac" in props


def test_tidak_ada_skema_lain_yang_membocorkan_kunci_jawaban(spec):
    leaks = {
        name: set(s.get("properties", {})) & SECRETS
        for name, s in spec["components"]["schemas"].items()
        if name not in ALLOWED and set(s.get("properties", {})) & SECRETS
    }
    assert not leaks, f"skema membocorkan kunci jawaban: {leaks}"


def test_rubrik_hanya_dikirim_sebagai_judul_kriteria(spec):
    props = spec["components"]["schemas"]["QuestionPublic"]["properties"]
    assert "rubric_criteria" in props
    assert "rubric" not in props


def test_seluruh_endpoint_kuis_membutuhkan_otorisasi(spec):
    public = {"/health", "/auth/register", "/auth/login", "/auth/refresh",
              "/devices/pair", "/devices/check-binding"}
    missing = []
    for path, ops in spec["paths"].items():
        if path in public:
            continue
        for verb, op in ops.items():
            has_auth = any(
                p.get("name", "").lower() == "authorization"
                for p in op.get("parameters", [])
            )
            if not has_auth:
                missing.append(f"{verb.upper()} {path}")
    assert not missing, f"endpoint tanpa header identitas: {missing}"


def test_semua_endpoint_terdaftar(spec):
    assert len(spec["paths"]) >= 30


def test_unggah_materi_mengantrekan_pekerjaan_setelah_transaksi_selesai():
    import inspect

    from app.routers import materials

    source = inspect.getsource(materials.upload_material)
    assert "tasks.add_task(Q.enqueue" in source, (
        "pekerjaan generate harus diantrekan lewat BackgroundTasks; kalau dipanggil "
        "langsung, worker bisa membacanya sebelum baris materi ter-commit"
    )
    assert "await Q.enqueue(" not in source


def test_orang_tua_punya_jalur_untuk_mengatur_dirinya_sendiri(spec):
    path = spec["paths"].get("/subjects/self")
    assert path, "orang tua harus bisa membuat subjek pribadinya sendiri"
    schema = path["post"]["responses"]["201"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/SubjectOut")


def test_menjawab_tidak_membocorkan_benar_salah(spec):
    body = spec["paths"]["/quizzes/{session_id}/answers"]["post"]
    ref = body["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    props = set(spec["components"]["schemas"][name]["properties"])
    leaks = props & {"is_correct", "score", "reward_seconds", "correct_index", "explanation"}
    assert not leaks, (
        f"jawaban dinilai saat dikumpulkan, bukan saat dijawab; {name} membocorkan {leaks}"
    )


def test_orang_tua_bukan_perantara_untuk_subjeknya_sendiri():
    from types import SimpleNamespace

    from app.deps import is_proxy

    me = SimpleNamespace(is_parent=True, user_id="u1")
    assert is_proxy(me, {"user_id": "u2"}), "subjek anak tetap dilindungi"
    assert not is_proxy(me, {"user_id": "u1"}), (
        "orang tua yang mengatur dirinya sendiri bukan perantara, jadi tidak "
        "boleh terkena penjaga privasi yang ditujukan untuk materi anak"
    )
    child = SimpleNamespace(is_parent=False, user_id=None)
    assert not is_proxy(child, {"user_id": None})
