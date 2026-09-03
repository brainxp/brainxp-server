from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.services.rules import StreakState, advance_streak


@dataclass(frozen=True)
class Badge:
    code: str
    name: str
    hint: str


BADGES: list[Badge] = [
    Badge("first", "Langkah Pertama", "Menyelesaikan sesi pertama"),
    Badge("week", "Sepekan Penuh", "Streak 7 hari"),
    Badge("month", "Sebulan Penuh", "Streak 30 hari"),
    Badge("hundred", "Seratus Hari", "Streak 100 hari"),
    Badge("fifty", "Lima Puluh", "50 soal dijawab benar"),
    Badge("five_hundred", "Lima Ratus", "500 soal dijawab benar"),
    Badge("essay", "Penakluk Esai", "10 esai lolos ambang"),
    Badge("hard", "Penantang", "25 soal sulit dijawab benar"),
    Badge("photo", "Juru Foto", "Materi pertama dari kamera"),
    Badge("cross", "Lintas Bahasa", "Materi asing menghasilkan soal bahasa lain"),
    Badge("perfect", "Nirsalah", "Satu sesi tanpa satu pun salah"),
]

_RULES = {
    "first": lambda p: p["sessions"] >= 1,
    "week": lambda p: p["streak_current"] >= 7,
    "month": lambda p: p["streak_current"] >= 30,
    "hundred": lambda p: p["streak_current"] >= 100,
    "fifty": lambda p: p["correct_total"] >= 50,
    "five_hundred": lambda p: p["correct_total"] >= 500,
    "essay": lambda p: p["essay_passed"] >= 10,
    "hard": lambda p: p["hard_total"] >= 25,
    "photo": lambda p: p["photo_total"] >= 1,
    "cross": lambda p: p["cross_lang"] >= 1,
    "perfect": lambda p: p["perfect_total"] >= 1,
}


async def ensure_row(db: AsyncConnection, subject_id: uuid.UUID) -> None:
    await db.execute(
        pg_insert(T.progress).values(subject_id=subject_id).on_conflict_do_nothing(
            index_elements=[T.progress.c.subject_id]
        )
    )


async def record_session(
    db: AsyncConnection,
    *,
    subject_id: uuid.UUID,
    day: date,
    correct: int,
    hard: int,
    essay_passed: int,
    from_photo: bool,
    cross_language: bool,
    perfect: bool,
) -> list[Badge]:
    await ensure_row(db, subject_id)
    row = (
        await db.execute(select(T.progress).where(T.progress.c.subject_id == subject_id))
    ).mappings().one()

    st = advance_streak(
        StreakState(row["streak_current"], row["streak_longest"],
                    row["freeze_tokens"], row["last_study_day"]),
        day,
    )

    updated = {
        "streak_current": st.current,
        "streak_longest": st.longest,
        "freeze_tokens": st.freeze_tokens,
        "last_study_day": st.last_study_day,
        "sessions": row["sessions"] + 1,
        "correct_total": row["correct_total"] + correct,
        "hard_total": row["hard_total"] + hard,
        "essay_passed": row["essay_passed"] + essay_passed,
        "photo_total": row["photo_total"] + (1 if from_photo else 0),
        "cross_lang": row["cross_lang"] + (1 if cross_language else 0),
        "perfect_total": row["perfect_total"] + (1 if perfect else 0),
    }
    await db.execute(
        T.progress.update().where(T.progress.c.subject_id == subject_id).values(**updated)
    )

    snapshot = {**dict(row), **updated}
    owned = {
        r[0] for r in (
            await db.execute(
                select(T.achievements.c.badge_code)
                .where(T.achievements.c.subject_id == subject_id)
            )
        ).all()
    }

    fresh: list[Badge] = []
    for b in BADGES:
        if b.code in owned:
            continue
        if _RULES[b.code](snapshot):
            await db.execute(
                pg_insert(T.achievements)
                .values(subject_id=subject_id, badge_code=b.code)
                .on_conflict_do_nothing(
                    index_elements=[T.achievements.c.subject_id, T.achievements.c.badge_code]
                )
            )
            fresh.append(b)
    return fresh
