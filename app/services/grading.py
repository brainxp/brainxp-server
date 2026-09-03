from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.llm import EssayVerdict, provider
from app.services.rules import ESSAY_PASS_SCORE

INJECTION_PATTERNS = [
    r"\babaikan\b[^.\n]{0,40}\b(instruksi|perintah|aturan|rubrik|sistem|sebelumnya|di\s*atas)\b",
    r"\bignore\b[^.\n]{0,40}\b(instructions?|previous|above|prompt|rules?)\b",
    r"\bdisregard\b[^.\n]{0,40}\b(instructions?|previous|above)\b",
    r"\bberi(?:kan)?\s+(?:aku\s+)?(?:nilai|skor)\s*(?:=|:)?\s*(?:100|penuh|sempurna|maksimal)\b",
    r"\bgive\s+(?:me\s+)?(?:a\s+)?(?:full|perfect|100)\s*(?:score|marks?|points?)\b",
    r"\byou\s+are\s+(?:now\s+)?(?:a|an|the)\b",
    r"^\s*(?:system|assistant|user)\s*:",
    r"<\/?(?:system|instruction|rubric)\b",
    r"\bnilai\s+(?:semua|seluruh)\s+kriteria\s+(?:sebagai\s+)?(?:terpenuhi|benar)\b",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE | re.MULTILINE)

MIN_ESSAY_WORDS = 8


@dataclass(frozen=True)
class EssayResult:
    score: float
    passed: bool
    injection_flag: bool
    notes: str

    @property
    def rewardable_score(self) -> float | None:
        return None if self.injection_flag else self.score


def detect_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


def grade_mcq(*, chosen_index: int | None, correct_index: int) -> bool:
    return chosen_index is not None and chosen_index == correct_index


async def grade_essay(
    *, stem: str, rubric: list[dict], reference_answer: str, answer: str
) -> EssayResult:
    text = (answer or "").strip()

    if not text:
        return EssayResult(0.0, False, False, "Jawaban kosong.")

    if detect_injection(text):
        return EssayResult(
            0.0, False, True,
            "Jawaban memuat pola instruksi kepada penilai. Ditandai dan tidak diberi reward.",
        )

    if len(text.split()) < MIN_ESSAY_WORDS:
        return EssayResult(0.0, False, False,
                           f"Jawaban terlalu singkat, minimal {MIN_ESSAY_WORDS} kata.")

    verdict: EssayVerdict = await provider().grade_essay(
        stem=stem, rubric=rubric, reference_answer=reference_answer, answer=text
    )

    score = max(0.0, min(100.0, float(verdict.total_score)))
    met = ", ".join(c.criterion for c in verdict.criteria if c.met) or "tidak ada"
    return EssayResult(
        score,
        score >= ESSAY_PASS_SCORE,
        False,
        f"Kriteria terpenuhi: {met}. {verdict.feedback}".strip(),
    )
