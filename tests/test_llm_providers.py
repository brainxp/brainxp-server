import json

import anthropic
import httpx2 as httpx
import pytest

from app.config import Settings
from app.errors import LLMRefused
from app.services import llm as L

TEXT = L.Attachment(media_type="text/plain", data=b"Fotosintesis mengubah cahaya menjadi energi kimia.")
PNG = L.Attachment(media_type="image/png", data=b"\x89PNG\r\n\x1a\n")
PDF = L.Attachment(media_type="application/pdf", data=b"%PDF-1.4")

VERDICT = {
    "is_study_material": True, "assessed_level": "smp", "concept_density": 0.5,
    "detected_language": "id", "topic_summary": "fotosintesis", "reject_reason": None,
}


def with_keys(anthropic_key: str = "", openrouter_key: str = "", **overrides) -> Settings:
    return Settings(
        anthropic_api_key=anthropic_key, openrouter_api_key=openrouter_key,
        _env_file=None, **overrides,
    )


def completion(content: str, finish: str = "stop", native: str = "end_turn") -> dict:
    return {"choices": [{
        "finish_reason": finish, "native_finish_reason": native,
        "message": {"role": "assistant", "content": content},
    }]}


def openrouter(handler, **overrides) -> L.OpenRouterProvider:
    return L.OpenRouterProvider(
        with_keys(openrouter_key="or-key", **overrides), transport=httpx.MockTransport(handler)
    )


class Recorder:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.request: httpx.Request | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return self.response

    @property
    def body(self) -> dict:
        assert self.request is not None
        return json.loads(self.request.content)


class FakeBackend:
    def __init__(self, name: str, outcome):
        self.name = name
        self.generation_model = f"{name}-model"
        self.outcome = outcome
        self.calls = 0

    async def _answer(self):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def validate_material(self, **kw):
        return await self._answer()

    async def generate_questions(self, **kw):
        return await self._answer()

    async def grade_essay(self, **kw):
        return await self._answer()


@pytest.mark.parametrize(("anthropic_id", "openrouter_id"), [
    ("claude-opus-5", "anthropic/claude-opus-5"),
    ("claude-haiku-4-5", "anthropic/claude-haiku-4.5"),
    ("claude-opus-4-8", "anthropic/claude-opus-4.8"),
    ("google/gemini-2.5-pro", "google/gemini-2.5-pro"),
])
def test_openrouter_asks_for_the_same_claude_models(anthropic_id, openrouter_id):
    assert L.openrouter_model(anthropic_id) == openrouter_id


def test_without_any_key_the_stub_answers():
    s = with_keys()
    assert isinstance(L.build_provider(s), L.StubProvider)
    assert s.llm_label == "stub"
    assert not s.llm_enabled


def test_anthropic_alone_runs_alone():
    s = with_keys(anthropic_key="a")
    assert type(L.build_provider(s)) is L.AnthropicProvider
    assert s.llm_label == "anthropic"


def test_openrouter_alone_runs_alone():
    s = with_keys(openrouter_key="o")
    assert type(L.build_provider(s)) is L.OpenRouterProvider
    assert s.llm_label == "openrouter"


def test_both_keys_put_anthropic_first_and_openrouter_behind_it():
    s = with_keys(anthropic_key="a", openrouter_key="o")
    p = L.build_provider(s)
    assert isinstance(p, L.FallbackProvider)
    assert isinstance(p.primary, L.AnthropicProvider)
    assert isinstance(p.backup, L.OpenRouterProvider)
    assert p.generation_model == "claude-opus-5"
    assert s.llm_label == "anthropic+openrouter"


async def test_the_backup_is_only_asked_when_the_primary_fails():
    primary = FakeBackend("primary", L.LLMUnavailable("anthropic: 529 overloaded"))
    backup = FakeBackend("backup", "from backup")
    result = await L.FallbackProvider(primary, backup).validate_material(att=TEXT, declared_level="smp")
    assert result == "from backup"
    assert (primary.calls, backup.calls) == (1, 1)


async def test_a_healthy_primary_never_wakes_the_backup():
    primary = FakeBackend("primary", "from primary")
    backup = FakeBackend("backup", "from backup")
    result = await L.FallbackProvider(primary, backup).grade_essay(
        stem="s", rubric=[], reference_answer="r", answer="a"
    )
    assert result == "from primary"
    assert backup.calls == 0


async def test_a_refusal_is_final_and_does_not_fall_through():
    primary = FakeBackend("primary", LLMRefused("cyber"))
    backup = FakeBackend("backup", "from backup")
    with pytest.raises(LLMRefused):
        await L.FallbackProvider(primary, backup).validate_material(att=TEXT, declared_level="smp")
    assert backup.calls == 0, "a refusal is a verdict on the material, not an outage"


async def test_when_both_fail_the_last_error_surfaces():
    primary = FakeBackend("primary", L.LLMUnavailable("anthropic: down"))
    backup = FakeBackend("backup", L.LLMUnavailable("openrouter: down"))
    with pytest.raises(L.LLMUnavailable, match="openrouter"):
        await L.FallbackProvider(primary, backup).generate_questions(
            att=TEXT, count=3, essays=1, academic_level="smp", language="id"
        )
    assert (primary.calls, backup.calls) == (1, 1)


async def test_openrouter_sends_the_gate_prompt_as_a_chat_completion():
    rec = Recorder(httpx.Response(200, json=completion(json.dumps(VERDICT))))
    verdict = await openrouter(rec).validate_material(att=PNG, declared_level="smp")

    assert verdict == L.GateVerdict(**VERDICT)
    assert str(rec.request.url) == L.OPENROUTER_URL
    assert rec.request.headers["authorization"] == "Bearer or-key"
    body = rec.body
    assert body["model"] == "anthropic/claude-haiku-4.5"
    assert body["max_tokens"] == 2000
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "GateVerdict"
    assert fmt["json_schema"]["strict"] is True
    assert "is_study_material" in fmt["json_schema"]["schema"]["properties"]
    system, user = body["messages"]
    assert system == {"role": "system", "content": L.GATE_SYSTEM}
    opens, image, closes = user["content"]
    assert opens == {"type": "text", "text": L.MATERIAL_OPENS}
    assert image["type"] == "image_url"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    assert closes["text"].startswith(L.MATERIAL_CLOSES)
    assert closes["text"].endswith("smp.")


async def test_openrouter_sends_a_pdf_as_a_file_part():
    rec = Recorder(httpx.Response(200, json=completion(json.dumps(VERDICT))))
    await openrouter(rec).validate_material(att=PDF, declared_level="sma")
    part = rec.body["messages"][1]["content"][1]
    assert part["type"] == "file"
    assert part["file"]["filename"].endswith(".pdf")
    assert part["file"]["file_data"].startswith("data:application/pdf;base64,")


async def test_openrouter_sends_text_material_inline():
    rec = Recorder(httpx.Response(200, json=completion(json.dumps(VERDICT))))
    await openrouter(rec).validate_material(att=TEXT, declared_level="smp")
    part = rec.body["messages"][1]["content"][1]
    assert part == {"type": "text", "text": TEXT.data.decode()}


async def test_openrouter_generation_uses_the_generation_model_and_budget():
    batch = {"questions": []}
    rec = Recorder(httpx.Response(200, json=completion(json.dumps(batch))))
    await openrouter(rec).generate_questions(
        att=TEXT, count=3, essays=1, academic_level="smp", language="id"
    )
    body = rec.body
    assert body["model"] == "anthropic/claude-opus-5"
    assert body["max_tokens"] == L.generation_token_budget(3)
    assert body["response_format"]["json_schema"]["name"] == "QuestionBatch"
    assert "Buat tepat 3 soal" in body["messages"][1]["content"][2]["text"]


async def test_an_openrouter_error_body_becomes_unavailable():
    error = {"error": {"message": "Missing Authentication header", "code": 401}}
    with pytest.raises(L.LLMUnavailable, match="401"):
        await openrouter(Recorder(httpx.Response(401, json=error))).validate_material(
            att=TEXT, declared_level="smp"
        )


async def test_a_non_json_body_from_openrouter_becomes_unavailable():
    with pytest.raises(L.LLMUnavailable, match="non-JSON"):
        await openrouter(Recorder(httpx.Response(502, text="<html>bad gateway</html>"))).validate_material(
            att=TEXT, declared_level="smp"
        )


async def test_a_dropped_connection_to_openrouter_becomes_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(L.LLMUnavailable, match="openrouter"):
        await openrouter(handler).validate_material(att=TEXT, declared_level="smp")


async def test_a_refusal_through_openrouter_is_a_refusal():
    rec = Recorder(httpx.Response(200, json=completion("", finish="content_filter", native="refusal")))
    with pytest.raises(LLMRefused):
        await openrouter(rec).validate_material(att=TEXT, declared_level="smp")


async def test_a_reply_off_schema_becomes_unavailable():
    rec = Recorder(httpx.Response(200, json=completion('{"nope": 1}')))
    with pytest.raises(L.LLMUnavailable, match="GateVerdict"):
        await openrouter(rec).validate_material(att=TEXT, declared_level="smp")


async def test_an_anthropic_api_error_becomes_unavailable(monkeypatch):
    p = L.AnthropicProvider(with_keys(anthropic_key="a"))

    async def boom(**kw):
        raise anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )

    monkeypatch.setattr(p, "_ask", boom)
    with pytest.raises(L.LLMUnavailable, match="anthropic"):
        await p.validate_material(att=TEXT, declared_level="smp")


def test_both_providers_build_from_one_prompt():
    req = L.gate_request(PNG, "smp")
    anthropic_blocks = L.AnthropicProvider.content(req.parts)
    openrouter_parts = [L.OpenRouterProvider.part(p) for p in req.parts]
    assert anthropic_blocks[0]["text"] == openrouter_parts[0]["text"] == L.MATERIAL_OPENS
    assert anthropic_blocks[1]["type"] == "image"
    assert anthropic_blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert openrouter_parts[1]["type"] == "image_url"
    assert anthropic_blocks[2]["text"] == openrouter_parts[2]["text"]
