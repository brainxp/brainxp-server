import ast
import re
from pathlib import Path

import pytest

from app.errors import Forbidden, LLMRefused, NotFound, RateLimited, TooLarge, Unauthorized

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [*sorted((ROOT / "app").rglob("*.py")), ROOT / "scripts" / "gen_openapi.py"]

INDONESIAN_WORDS = (
    "tidak", "belum", "sudah", "yang", "untuk", "dengan", "gagal", "berkas", "jalankan",
    "menerapkan", "mengembalikan", "menunggu", "kedaluwarsa", "dikenal", "dibuang",
    "menolak", "cadangan", "penyedia", "pekerjaan", "perangkat", "antrean", "tertinggal",
    "mutakhir", "tertunda", "memakai", "dipakai", "ganti", "coba", "hangus", "galat",
    "aplikasi", "aturan", "saldo", "soal", "materi", "kunci",
)
PATTERN = re.compile(r"\b(" + "|".join(INDONESIAN_WORDS) + r")\b", re.I)

LOG_LEVELS = {"info", "warning", "error", "exception", "debug", "critical"}
RAW_ERRORS = {"RuntimeError", "ValueError", "TypeError", "NotImplementedError"}


def literal_text(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return " ".join(
            part.value for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def reaches_a_developer(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        return isinstance(owner, ast.Name) and owner.id == "log" and func.attr in LOG_LEVELS
    if isinstance(func, ast.Name):
        return func.id in RAW_ERRORS or func.id == "print"
    return False


def developer_messages():
    found = []
    for path in SOURCES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not reaches_a_developer(node):
                continue
            for arg in node.args:
                text = literal_text(arg)
                if text:
                    found.append((path.relative_to(ROOT).as_posix(), node.lineno, text))
    return found


MESSAGES = developer_messages()


def test_the_developer_messages_were_actually_collected():
    assert len(MESSAGES) >= 20, f"only {len(MESSAGES)} collected, the reader is probably broken"


@pytest.mark.parametrize(
    "path,line,text", MESSAGES, ids=lambda v: str(v) if not isinstance(v, str) else v[:40]
)
def test_a_message_for_developers_is_written_in_english(path, line, text):
    caught = sorted({m.lower() for m in PATTERN.findall(text)})
    assert not caught, (
        f"{path}:{line} uses the Indonesian word(s) {caught} in a message only a "
        f"developer reads: {text!r}"
    )


USER_FACING = [Unauthorized, Forbidden, NotFound, TooLarge, RateLimited, LLMRefused]


@pytest.mark.parametrize("error", USER_FACING, ids=lambda e: e.__name__)
def test_a_message_for_users_stays_in_indonesian(error):
    message = error().detail["message"]
    assert PATTERN.search(message), (
        f"{error.__name__} answers '{message}' to an end user. An HTTP response body "
        "is read by parents and children, so it stays in Indonesian"
    )


def test_the_500_body_stays_in_indonesian():
    source = (ROOT / "app" / "main.py").read_text()
    assert '"message": "Terjadi galat di server."' in source, (
        "the 500 body reaches a user, unlike the log.exception just above it"
    )
