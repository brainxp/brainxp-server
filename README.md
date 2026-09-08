# BrainXP

Backend for an app that locks your games until you answer questions drawn from
the material you are actually studying. The questions come from whatever you
upload, so they are never generic.

The short version: you hold a balance of play time. When it runs out, the app
locks. To top it up you hand in study material — a photo of your notes, or a
PDF, DOCX or PPTX — questions get built from it, you answer them, and the
minutes land in your balance.

Two modes. Family: a parent sets the rules and the child just lives with them.
Personal: you set your own rules, but loosening any of them takes 24 hours to
kick in.

## Running it

You need Docker. Copy `.env.example` to `.env`, fill in the blanks, then:

```bash
docker compose up -d
docker compose run --rm api python -m app.migrate
```

Set `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or both. With both, every call
goes to Anthropic first and falls back to OpenRouter when Anthropic fails with
a network or API error. OpenRouter serves the same Claude models under its
`anthropic/` prefix, so there is no second set of model names to keep in step.
Leave both empty and the backend still runs on a stub provider. Handy for
walking the whole flow without paying for API calls. Check `/health` to see
which of them is live.

Every deploy writes `OPENROUTER_API_KEY` into the server's `.env` from the
GitHub secret of the same name, so nobody types it in by hand.

The same goes for `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT`: leave them empty
and guardian alerts are still raised and readable over the API, they just are
not pushed to anyone's phone.

For a server there is `deploy/provision.sh` (run once, as root) and
`deploy/bootstrap.sh` (sets up Garage, migrates, brings everything up).

## Layout

```
app/services/rules.py      reward maths, level calibration, streaks. pure
                           functions, no database, so they are easy to test
app/services/llm.py        Claude integration
app/services/grading.py    multiple choice and essay marking
app/services/generation.py question pipeline, runs on the worker
app/routers/               endpoints
migrations/                database schema
deploy/                    server scripts, nginx config
```

## Things worth knowing before you touch it

The balance is never stored as a single number. Everything goes into an
append-only `time_ledger` and the balance is a SUM. That makes reconciling an
offline phone straightforward, and no figure can quietly drift.

Answer keys never reach the client. `QuestionPublic` in `app/schemas.py` has no
field for them at all — not merely left unset. There is a test for it in
`tests/test_api_contract.py`.

The essay marker never sees the source material, only the rubric and the
student's answer. The rubric is frozen when the question is written, long
before any answer exists.

Photograph a handout page by page and it arrives as one material. The upload
endpoint takes several parts named `file`, and more than one has to be photos.
The server stitches them into a single PDF before anything else touches them,
so six photos give one question set and one quiz session, and a question can
come from any of the pages. It turns each page upright from its EXIF
orientation and scales it to the model's vision limit, which is why the merged
PDF usually comes out smaller than the photos that went in.

Migrations are append-only. Add a new
`migrations/<YYYYMMDDHHMMSS>_<verb>_<what>.up.sql` together with its
`.down.sql`. A `create_` file makes exactly one table. Never edit one that has
already run.

## Tests

```bash
uv pip install -e ".[dev]"
pytest -q
ruff check app tests scripts
```

136 tests, all of which run without a database, without Redis, without an API
key.

If you change the API, regenerate the spec:

```bash
python scripts/gen_openapi.py
```

`openapi.json` and `API.md` are built from the source. Only `openapi.json` is
committed, and a test fails when it drifts from the routers. `API.md` is a
local copy for reading and stays out of git.

## Branches

`main` holds only this README. All the code lives on `dev`.

To add something, branch off `dev` (`feat/your-thing`) and open a PR back into
`dev`. Don't push straight to `dev`.

## Not done yet

There is no way to dispute a wrong answer key. Material similarity still
compares topic summaries rather than embeddings, since Anthropic offers no
embedding endpoint. The offline question bank can be fetched, but pre-generating
it through the Batch API is not wired up. There are no integration tests; every
test is a unit test.
