# BrainXP — Spesifikasi API

Versi 0.1.0. 36 operasi pada 32 path.

Berkas ini dibangkitkan dari kode oleh `scripts/gen_openapi.py`. Jangan disunting langsung — ubah routernya, lalu jalankan skripnya.
Sumber kebenarannya adalah `openapi.json`; berkas ini hanya versi yang enak dibaca.

Seluruh operasi memakai JSON kecuali unggah materi yang memakai multipart. Otorisasi memakai header `Authorization: Bearer <access_token>`.

## Autentikasi

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `POST /auth/login` | — | `LoginIn` | 200 `TokenOut` |
| `POST /auth/logout` | Bearer | `RefreshIn` | 204 |
| `POST /auth/refresh` | — | `RefreshIn` | 200 `TokenOut` |
| `POST /auth/register` | — | `RegisterIn` | 201 `TokenOut` |

## Keluarga, subjek, dan perangkat

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `POST /devices/check-binding` | — | `BindingCheckIn` | 200 `BindingCheckOut` |
| `POST /devices/heartbeat` | Bearer | `HeartbeatIn` | 204 |
| `POST /devices/pair` | — | `PairIn` | 200 `TokenOut` |
| `GET /subjects` | Bearer | — | 200 `SubjectOut[]` |
| `POST /subjects` | Bearer | `ChildIn` | 201 `SubjectOut` |
| `POST /subjects/self` | Bearer | `SelfSubjectIn` | 201 `SubjectOut` |
| `POST /subjects/{subject_id}/pairing-code` | Bearer | — | 200 `PairingCodeOut` |

## Aturan

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `GET /policies/{subject_id}` | Bearer | — | 200 `PolicyOut` |
| `PUT /policies/{subject_id}` | Bearer | `PolicyIn` | 200 `PolicyChangeOut` |
| `DELETE /policies/{subject_id}/locked-apps/{package}` | Bearer | — | 200 `PolicyChangeOut` |
| `POST /policies/{subject_id}/locked-apps/{package}` | Bearer | — | 200 `PolicyChangeOut` |
| `DELETE /policies/{subject_id}/pending` | Bearer | — | 200 `PolicyChangeOut` |
| `POST /policies/{subject_id}/pending/apply` | Bearer | — | 200 `PolicyChangeOut` |

## Materi

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `DELETE /materials/{material_id}` | Bearer | — | 204 |
| `GET /materials/{material_id}` | Bearer | — | 200 `MaterialOut` |
| `GET /materials/{material_id}/file` | Bearer | — | 200 |
| `PATCH /materials/{material_id}/retention` | Bearer | `RetentionIn` | 200 `MaterialOut` |
| `GET /materials/{material_id}/stream` | Bearer | — | 200 |
| `GET /subjects/{subject_id}/library` | Bearer | — | 200 `MaterialOut[]` |
| `POST /subjects/{subject_id}/materials` | Bearer | berkas (multipart) | 202 `MaterialAcceptedOut` |

## Kuis dan penilaian

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `GET /quizzes/{session_id}` | Bearer | — | 200 `QuizOut` |
| `POST /quizzes/{session_id}/answers` | Bearer | `AnswerIn` | 200 `AnswerSavedOut` |
| `POST /quizzes/{session_id}/submit` | Bearer | — | 200 `ReceiptOut` |
| `GET /subjects/{subject_id}/offline-bank` | Bearer | — | 200 `OfflineQuestionOut[]` |
| `POST /subjects/{subject_id}/quizzes` | Bearer | `QuizStartIn` | 201 `QuizOut` |

## Saldo dan ekonomi waktu

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `GET /subjects/{subject_id}/ledger` | Bearer | — | 200 `LedgerEntryOut[]` |
| `POST /subjects/{subject_id}/ledger/adjust` | Bearer | `AdjustIn` | 200 `StandingOut` |
| `POST /subjects/{subject_id}/ledger/sync` | Bearer | `ConsumptionIn[]` | 200 `StandingOut` |
| `GET /subjects/{subject_id}/standing` | Bearer | — | 200 `StandingOut` |

## Laporan dan kemajuan

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `GET /subjects/{subject_id}/progress` | Bearer | — | 200 `ProgressOut` |
| `GET /subjects/{subject_id}/report` | Bearer | — | 200 `ReportOut` |

## Operasional

| Operasi | Auth | Kirim | Terima |
|---|---|---|---|
| `GET /health` | — | — | 200 |

## Skema

- **AdjustIn** — `direction`, `note`, `seconds`
- **AnswerIn** — `chosen_index`?, `essay_text`?, `question_id`
- **AnswerSavedOut** — `answered_count`, `question_id`, `total_count`
- **BadgeOut** — `code`, `earned`, `earned_at`?, `hint`, `name`
- **BindingCheckIn** — `install_binding`
- **BindingCheckOut** — `bound`, `family_mode`?, `subject_name`?
- **Body_upload_material_subjects__subject_id__materials_post** — `file`, `method`?
- **ChildIn** — `academic_level`?, `display_name`, `question_language`?
- **ConsumptionIn** — `app_label`, `client_event_id`, `occurred_at`?, `seconds`
- **DayPointOut** — `consumed_seconds`, `day`, `earned_seconds`
- **HTTPValidationError** — `detail`?
- **HeartbeatIn** — `events`?, `guardian_status`
- **LedgerEntryOut** — `delta_seconds`, `entry_type`, `note`, `occurred_at`
- **LoginIn** — `email`, `password`
- **MaterialAcceptedOut** — `duplicate_of`?, `material_id`, `status`
- **MaterialOut** — `assessed_level`?, `concept_density`?, `created_at`, `declared_level`?, `detected_language`?, `gate_reason`?, `gate_verdict`?, `id`, `novelty_score`?, `original_name`, `page_count`?, `question_count`?, `retention_mode`, `source_type`, `status`, `times_studied`?, `topic_summary`?
- **OfflineQuestionOut** — `answer_hmac`, `difficulty`, `id`, `options`, `qtype`, `source_excerpt`, `stem`
- **PairIn** — `code`, `install_binding`, `model_name`?, `platform`?
- **PairingCodeOut** — `attempts_allowed`, `code`, `expires_at`, `subject_id`
- **PolicyChangeOut** — `applied`, `message`, `pending_until`?
- **PolicyIn** — `academic_level`?, `allowed_upload_methods`?, `base_reward_seconds`?, `daily_caps`?, `daily_grants`?, `day_reset_hour`?, `essay_ratio`?, `idle_days_allowed`?, `locked_apps`?, `question_language`?, `questions_per_session`?
- **PolicyOut** — `academic_level`, `allowed_upload_methods`, `base_reward_seconds`, `daily_caps`, `daily_grants`, `day_reset_hour`, `essay_ratio`, `idle_days_allowed`, `locked_apps`, `pending_weaken_at`?, `pending_weaken_payload`?, `question_language`, `questions_per_session`, `subject_id`
- **ProgressOut** — `badges`, `correct_total`, `essay_passed`, `freeze_tokens`, `sessions`, `streak_current`, `streak_longest`, `subject_id`
- **QuestionPublic** — `bloom_level`, `difficulty`, `difficulty_factor`, `id`, `options`?, `ordinal`, `qtype`, `rubric_criteria`?, `source_excerpt`, `stem`, `type_factor`
- **QuizOut** — `answered_ids`?, `base_reward_seconds`, `level_factor`, `material_id`, `max_reward_seconds`, `novelty_factor`, `questions`, `ready_count`, `session_id`, `status`, `title`, `total_count`
- **QuizStartIn** — `material_id`
- **ReceiptOut** — `balance_seconds`, `base_reward_seconds`, `correct_count`, `credited_seconds`, `gross_seconds`, `level_factor`, `level_note`, `new_badges`, `novelty_factor`, `novelty_note`, `question_count`, `rows`, `session_id`, `streak_current`, `subtotal_seconds`, `title`
- **ReceiptRow** — `difficulty`, `explanation`?, `label`, `multiplier`, `ordinal`, `qtype`, `reward_seconds`, `score`?, `void_reason`?, `voided`?
- **RefreshIn** — `refresh_token`
- **RegisterIn** — `display_name`, `email`, `mode`?, `password`
- **ReportOut** — `correct_total`, `days`, `essay_passed`, `guardian_alerts`, `materials_studied`, `recent`, `standing`, `subject`
- **RetentionIn** — `retention_mode`
- **SelfSubjectIn** — `academic_level`?, `question_language`?
- **StandingOut** — `balance_seconds`, `block_reason`, `daily_cap_seconds`, `freeze_tokens`, `idle_days`, `idle_days_allowed`, `playable_seconds`, `seconds_until_reset`, `spent_today_seconds`, `streak_current`
- **SubjectOut** — `academic_level`, `display_name`, `id`, `kind`
- **TokenOut** — `access_token`, `device_secret`?, `expires_in`, `family_id`?, `refresh_token`, `role`, `subject_id`?, `user_id`?
- **ValidationError** — `ctx`?, `input`?, `loc`, `msg`, `type`

## Yang tidak pernah dikirim ke klien

`correct_index`, `rubric`, dan `reference_answer` tidak muncul pada skema mana pun selain `AnswerFeedbackOut`, yang hanya dikembalikan setelah sebuah soal dijawab. Aturan ini dijaga `tests/test_api_contract.py`.
