from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select

from app import tables as T
from app.db import dispose, engine
from app.security import now

log = logging.getLogger("brainxp.question_reports")

OPTION_LETTERS = "ABCD"


def actual_choice(row: Mapping[str, Any]) -> int | None:
    picked = row["chosen_index"]
    if picked is None:
        return None
    permutation = list((row["option_permutation"] or {}).get(str(row["question_id"]), []))
    return permutation[picked] if picked < len(permutation) else picked


def entry(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "report_id": row["id"],
        "reported_at": row["updated_at"].isoformat(),
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        "reason": row["reason"],
        "note": row["note"],
        "reporter_role": row["reporter_role"],
        "material": row["topic_summary"],
        "question_id": str(row["question_id"]),
        "session_id": str(row["session_id"]),
        "qtype": row["qtype"],
        "difficulty": row["difficulty"],
        "stem": row["stem"],
        "options": row["options"],
        "correct_index": row["correct_index"],
        "chosen_index": actual_choice(row),
        "essay_text": row["essay_text"],
        "reference_answer": row["reference_answer"],
        "rubric": row["rubric"],
        "is_correct": row["is_correct"],
        "score": float(row["score"]) if row["score"] is not None else None,
        "evaluator_notes": row["evaluator_notes"],
        "explanation": row["explanation"],
        "source_excerpt": row["source_excerpt"],
    }


def option_lines(item: Mapping[str, Any]) -> list[str]:
    lines = []
    for index, option in enumerate(item["options"] or []):
        marks = []
        if index == item["correct_index"]:
            marks.append("key")
        if index == item["chosen_index"]:
            marks.append("picked")
        suffix = f"   <- {', '.join(marks)}" if marks else ""
        lines.append(f"  {OPTION_LETTERS[index]}. {option}{suffix}")
    return lines


def essay_lines(item: Mapping[str, Any]) -> list[str]:
    return [
        f"  answer:    {item['essay_text'] or '-'}",
        f"  reference: {item['reference_answer'] or '-'}",
        f"  score:     {item['score'] if item['score'] is not None else '-'}",
        f"  marker:    {item['evaluator_notes'] or '-'}",
    ]


def verdict(is_correct: bool | None) -> str:
    if is_correct is None:
        return "not yet"
    return "correct" if is_correct else "wrong"


def render(item: Mapping[str, Any]) -> str:
    stamp = datetime.fromisoformat(item["reported_at"]).strftime("%Y-%m-%d %H:%M")
    body = option_lines(item) if item["qtype"] == "mcq" else essay_lines(item)
    return "\n".join([
        f"#{item['report_id']}  {item['reason']}  {stamp}  by {item['reporter_role']}",
        f"  material:  {item['material'] or '-'}",
        f"  question:  {item['stem']}",
        *body,
        f"  graded:    {verdict(item['is_correct'])}",
        f"  note:      {item['note'] or '-'}",
        f"  excerpt:   {item['source_excerpt']}",
        f"  ids:       question {item['question_id']}, session {item['session_id']}",
    ])


def listing(*, include_reviewed: bool, limit: int):
    R, Q, A = T.question_reports, T.questions, T.quiz_answers
    stmt = (
        select(
            R.c.id, R.c.session_id, R.c.question_id, R.c.reason, R.c.note,
            R.c.reporter_role, R.c.updated_at, R.c.reviewed_at,
            Q.c.qtype, Q.c.difficulty, Q.c.stem, Q.c.options, Q.c.correct_index,
            Q.c.reference_answer, Q.c.rubric, Q.c.explanation, Q.c.source_excerpt,
            T.materials.c.topic_summary, T.quiz_sessions.c.option_permutation,
            A.c.chosen_index, A.c.essay_text, A.c.is_correct, A.c.score, A.c.evaluator_notes,
        )
        .join(Q, Q.c.id == R.c.question_id)
        .join(T.quiz_sessions, T.quiz_sessions.c.id == R.c.session_id)
        .join(T.question_sets, T.question_sets.c.id == Q.c.question_set_id)
        .join(T.materials, T.materials.c.id == T.question_sets.c.material_id)
        .outerjoin(A, and_(A.c.session_id == R.c.session_id, A.c.question_id == R.c.question_id))
        .order_by(R.c.updated_at)
        .limit(limit)
    )
    return stmt if include_reviewed else stmt.where(R.c.reviewed_at.is_(None))


def mark_reviewed(ids: Sequence[int]):
    return (
        T.question_reports.update()
        .where(T.question_reports.c.id.in_(ids), T.question_reports.c.reviewed_at.is_(None))
        .values(reviewed_at=now())
    )


def arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.question_reports",
        description="List reported questions for manual review.",
    )
    parser.add_argument("--all", action="store_true", help="include reports already reviewed")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--jsonl", action="store_true", help="one JSON object per line")
    parser.add_argument("--done", type=int, nargs="+", metavar="ID",
                        help="mark these reports as reviewed")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    async with engine().begin() as conn:
        if args.done:
            marked = (await conn.execute(mark_reviewed(args.done))).rowcount
            log.info("marked %d report(s) as reviewed", marked)
            return 0
        rows = (
            await conn.execute(listing(include_reviewed=args.all, limit=args.limit))
        ).mappings().all()

    items = [entry(r) for r in rows]
    if args.jsonl:
        for item in items:
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if not items:
        log.info("no reports waiting for review")
        return 0
    print("\n\n".join(render(item) for item in items))
    return 0


async def main(argv: Sequence[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return await run(arguments(argv))
    finally:
        await dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
