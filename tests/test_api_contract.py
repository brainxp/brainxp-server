import pytest

from app.main import api

SECRETS = {"correct_index", "rubric", "reference_answer"}

ALLOWED: set[str] = set()


@pytest.fixture(scope="module")
def spec():
    return api.openapi()


def test_the_public_question_schema_has_no_room_for_the_answer_key(spec):
    props = set(spec["components"]["schemas"]["QuestionPublic"]["properties"])
    assert not (props & SECRETS), f"QuestionPublic leaks {props & SECRETS}"


def test_the_offline_bank_only_sends_an_hmac(spec):
    props = set(spec["components"]["schemas"]["OfflineQuestionOut"]["properties"])
    assert not (props & SECRETS)
    assert "answer_hmac" in props


def test_no_other_schema_leaks_the_answer_key(spec):
    leaks = {
        name: set(s.get("properties", {})) & SECRETS
        for name, s in spec["components"]["schemas"].items()
        if name not in ALLOWED and set(s.get("properties", {})) & SECRETS
    }
    assert not leaks, f"schemas leaking the answer key: {leaks}"


def test_the_rubric_is_sent_as_criterion_titles_only(spec):
    props = spec["components"]["schemas"]["QuestionPublic"]["properties"]
    assert "rubric_criteria" in props
    assert "rubric" not in props


def test_every_quiz_endpoint_requires_authorization(spec):
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
    assert not missing, f"endpoints without an identity header: {missing}"


def test_every_endpoint_is_registered(spec):
    assert len(spec["paths"]) >= 30


def test_uploading_material_queues_the_job_after_the_transaction_closes():
    import inspect

    from app.routers import materials

    source = inspect.getsource(materials.upload_material)
    assert "tasks.add_task(Q.enqueue" in source, (
        "the generate job has to be queued through BackgroundTasks; called directly, "
        "the worker can read it before the material row is committed"
    )
    assert "await Q.enqueue(" not in source


def test_a_parent_has_a_path_to_manage_themselves(spec):
    path = spec["paths"].get("/subjects/self")
    assert path, "a parent must be able to create their own personal subject"
    schema = path["post"]["responses"]["201"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/SubjectOut")


def test_answering_does_not_leak_right_or_wrong(spec):
    body = spec["paths"]["/quizzes/{session_id}/answers"]["post"]
    ref = body["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    props = set(spec["components"]["schemas"][name]["properties"])
    leaks = props & {"is_correct", "score", "reward_seconds", "correct_index", "explanation"}
    assert not leaks, (
        f"answers are marked on submission, not as they are given; {name} leaks {leaks}"
    )


def test_a_parent_is_not_a_proxy_for_their_own_subject():
    from types import SimpleNamespace

    from app.deps import is_proxy

    me = SimpleNamespace(is_parent=True, user_id="u1")
    assert is_proxy(me, {"user_id": "u2"}), "a child subject stays protected"
    assert not is_proxy(me, {"user_id": "u1"}), (
        "a parent managing themselves is not a proxy, so the privacy guard meant "
        "for a child's material must not apply to them"
    )
    child = SimpleNamespace(is_parent=False, user_id=None)
    assert not is_proxy(child, {"user_id": None})


def test_questions_per_session_is_capped_at_ten(spec):
    field = spec["components"]["schemas"]["PolicyIn"]["properties"]["questions_per_session"]
    bounds = next(v for v in field["anyOf"] if v.get("type") == "integer")
    assert bounds["maximum"] == 10, "the limit shown on screen has to be enforced by the API too"
    assert bounds["minimum"] == 1


def test_a_registration_password_is_at_least_eight_characters(spec):
    field = spec["components"]["schemas"]["RegisterIn"]["properties"]["password"]
    assert field["minLength"] == 8, (
        "the length asked for on the sign-up screen has to match what the API enforces"
    )


def test_the_pairing_code_names_the_device_already_registered(spec):
    schema = spec["components"]["schemas"]["PairingCodeOut"]["properties"]
    assert "bound_device" in schema, (
        "a parent has to know another device exists before handing over the code, "
        "because pairing a new one throws the old one out"
    )


def test_removing_a_profile_is_available_and_returns_no_body(spec):
    delete = spec["paths"]["/subjects/{subject_id}"].get("delete")
    assert delete, "a parent must be able to remove a child profile"
    assert "204" in delete["responses"]
