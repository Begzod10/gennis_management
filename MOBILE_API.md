# Mobile API

Unified API surface for the mobile app spanning three backends:
`management` (FastAPI), `gennis` (Flask), `turon` (Django).

All endpoints live under `/api/v1` and require `Authorization: Bearer <access_token>`
**except** `POST /mobile/auth/login` and `POST /mobile/auth/refresh`.

The JWT carries `{system, external_id, management_user_id, name, role}` so every
handler knows which DB to read from based on who is calling.

---

## Conventions

- `source` / `system` field on every response: one of `"management" | "gennis" | "turon"`.
- Dates use `YYYY-MM-DD`. Timestamps are ISO 8601 in UTC.
- Status values for a mission: `"pending" | "in_progress" | "completed" | "approved" | "declined"`.
- Error envelope: `{ "detail": "<message>" }` with the appropriate HTTP status.

### Common errors

| Status | Meaning                                                                  |
|--------|--------------------------------------------------------------------------|
| 400    | Bad payload (empty update, etc.)                                         |
| 401    | Missing / invalid / expired token                                        |
| 403    | You're not a participant on this mission (creator / executor / reviewer) |
| 404    | Mission / subtask not found in your home DB                              |
| 422    | Pydantic validation failed                                               |

---

## 1. Auth

### POST `/api/v1/mobile/auth/login`

No auth header required.

**Request**
```json
{
  "system": "management",
  "username": "alice@example.com",
  "password": "S3cret!"
}
```

`username` is:
- `management` → email
- `gennis` → username
- `turon` → phone

**Response 200**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": 12,
    "system": "management",
    "name": "Alice",
    "surname": "Doe",
    "role": "director"
  }
}
```

**Errors:** `401` invalid credentials.

---

### POST `/api/v1/mobile/auth/refresh`

No auth header required (the refresh token IS the credential).

**Request**
```json
{ "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

**Response 200** — same shape as login. Returns a fresh access + refresh pair (rotation).

**Errors:** `401` refresh token invalid / expired / user deactivated.

---

## 2. /me

### GET `/api/v1/mobile/me`

**Response 200**
```json
{
  "id": 12,
  "system": "management",
  "name": "Alice",
  "surname": "Doe",
  "email": "alice@example.com",
  "phone": null,
  "username": null,
  "role": "director",
  "telegram_linked": true,
  "telegram_id": 123456789
}
```

Field availability per system:

| Field        | management | gennis    | turon |
|--------------|------------|-----------|-------|
| email        | ✓          | —         | —     |
| username     | —          | ✓         | —     |
| phone        | —          | —         | ✓     |
| role         | ✓          | —         | —     |

---

### PATCH `/api/v1/mobile/me`

Partial update. Send only the fields you want to change. Fields not relevant
to your system are silently ignored (so a single client payload shape works
against any backend).

**Request**
```json
{
  "name": "Alicia",
  "surname": "Doe",
  "email": "alicia@example.com"
}
```

**Response 200** — same shape as GET `/me`.

**Errors:** `400` empty payload, `404` user not found.

---

### POST `/api/v1/mobile/me/change-password`

**Request**
```json
{
  "current_password": "S3cret!",
  "new_password": "EvenS3cret-er!"
}
```

`new_password` must be ≥ 6 chars. The new hash is written in your system's
native scheme so you can still log in via the source-system's web UI:
- management → bcrypt
- gennis → `pbkdf2:sha256:600000$<salt>$<hex>` (Werkzeug)
- turon → `pbkdf2_sha256$600000$<salt>$<b64>` (Django)

**Response 204** — empty body.

**Errors:** `401` current password incorrect.

---

## 3. Telegram linking

### POST `/api/v1/mobile/telegram/generate-link-code`

Mints a one-time code; mobile client opens the returned deep link in Telegram.

**Response 200**
```json
{
  "code": "Xa3kP9bQ",
  "expires_in": 300,
  "deep_link": "https://t.me/gennis_office_bot?start=Xa3kP9bQ",
  "tg_link": "tg://resolve?domain=gennis_office_bot&start=Xa3kP9bQ",
  "instruction": "Telegram botga /start Xa3kP9bQ yuboring"
}
```

The user sends `/start <code>` to the bot; the bot's webhook resolves the
code and stores the binding (management → `user.telegram_id`,
gennis/turon → `mobile_telegram_link` bridge table).

---

### GET `/api/v1/mobile/telegram/status`

**Response 200**
```json
{ "linked": true, "telegram_id": 123456789 }
```

---

### DELETE `/api/v1/mobile/telegram/unlink`

**Response 200**
```json
{ "detail": "Telegram hisobi uzildi" }
```

If not currently linked: `{"detail": "Telegram allaqachon uzilgan"}`.

---

## 4. Missions

### GET `/api/v1/mobile/missions/`

List missions you participate on (creator / executor / reviewer), from your
home DB.

**Query params:**
- `status` (optional) — filter by status
- `role` (optional) — `"executor" | "creator" | "reviewer"` to scope the list
- `limit` (default 50), `offset` (default 0)

**Response 200**
```json
{
  "total": 3,
  "results": [
    {
      "id": 47,
      "source": "management",
      "management_id": 47,
      "title": "Update onboarding deck",
      "description": "Refresh slides 12–18 with Q4 metrics",
      "category": "marketing",
      "status": "in_progress",
      "creator_id": 12,
      "creator_name": "Alice Doe",
      "executor_id": 18,
      "executor_name": "Bob Lee",
      "reviewer_id": 12,
      "reviewer_name": "Alice Doe",
      "location_id": null,
      "branch_id": null,
      "deadline": "2026-06-10",
      "finish_date": null,
      "kpi_weight": 10,
      "delay_days": 0,
      "final_sc": 0,
      "created_at": "2026-05-20T09:14:11Z"
    }
  ]
}
```

---

### GET `/api/v1/mobile/missions/{mission_id}`

Single mission detail.

**Response 200** — same shape as a list entry above.

**Errors:** `404` not found.

---

### POST `/api/v1/mobile/missions/`

Create a mission in your home system.

**Request**
```json
{
  "title": "Quarterly retro deck",
  "description": "Pull metrics and prep talking points",
  "category": "internal",
  "executor_id": 18,
  "reviewer_id": 12,
  "deadline": "2026-06-30",
  "kpi_weight": 10
}
```

`executor_id` / `reviewer_id` are **user ids in your home system** (gennis
users for gennis callers, etc.).

**Response 201** — single `MobileMissionOut`.

Notifications fired: assigned → executor; you-are-reviewer → reviewer
(if linked to Telegram).

---

### PATCH `/api/v1/mobile/missions/{mission_id}`

Partial update. Caller must be creator / executor / reviewer.

**Request** — any subset:
```json
{
  "title": "Q3 retro deck",
  "deadline": "2026-07-15",
  "executor_id": 22
}
```

**Response 200** — updated mission.

**Errors:** `400` empty payload, `403` not a participant, `404` not found.

---

### DELETE `/api/v1/mobile/missions/{mission_id}`

Soft delete (`deleted = true`). Caller must be a participant.

**Response 204** — empty.

**Errors:** `403`, `404`.

---

### PATCH `/api/v1/mobile/missions/{mission_id}/status`

Move a mission to a new status. Caller must be a participant.

**Request**
```json
{
  "status": "in_progress",
  "finish_date": null
}
```

For `completed`, supply a `finish_date` (server falls back to today if omitted).

**Response 200** — updated mission.

**Errors:** `403`, `404`.

---

### POST `/api/v1/mobile/missions/{mission_id}/complete`

Mark completed. **Executor only.**

**Request**
```json
{ "finish_date": "2026-06-09" }
```

**Response 200** — updated mission.

**Errors:** `403` not executor, `404`.

---

### PATCH `/api/v1/mobile/missions/{mission_id}/approve`

Approve or decline. **Reviewer or creator only.**

**Request**
```json
{ "approval_status": "approved" }
```

`approval_status` ∈ `"approved" | "declined"`.

**Response 200** — updated mission.

**Errors:** `403` not reviewer/creator, `404`.

---

### PATCH `/api/v1/mobile/missions/{mission_id}/redirect`

Reassign to a new executor. **Creator only.**

**Request**
```json
{ "new_executor_id": 31 }
```

**Response 200** — updated mission.

**Errors:** `403` not creator, `404` mission or new executor not found.

---

## 5. Mission events — read

### GET `/api/v1/mobile/missions/{mission_id}/history`

**Response 200**
```json
[
  {
    "id": 101,
    "source": "management",
    "status": "in_progress",
    "note": "status: pending -> in_progress (mobile)",
    "changed_by_name": "Bob Lee",
    "executor_name": "Bob Lee",
    "reviewer_name": "Alice Doe",
    "created_at": "2026-05-21T11:42:08Z"
  }
]
```

---

### GET `/api/v1/mobile/missions/{mission_id}/comments`

**Response 200**
```json
[
  {
    "id": 14,
    "source": "management",
    "text": "First draft uploaded — please review",
    "user_id": 18,
    "user_name": "Bob Lee",
    "attachment_path": "/uploads/comments/14.pdf",
    "created_at": "2026-05-22T08:30:00Z"
  }
]
```

---

### GET `/api/v1/mobile/missions/{mission_id}/attachments`

**Response 200**
```json
[
  {
    "id": 7,
    "source": "management",
    "file_path": "/uploads/missions/47/spec.pdf",
    "note": "Original brief",
    "creator_name": "Alice Doe",
    "uploaded_at": "2026-05-20T09:20:00Z"
  }
]
```

---

### GET `/api/v1/mobile/missions/{mission_id}/proofs`

**Response 200**
```json
[
  {
    "id": 3,
    "source": "management",
    "file_path": "/uploads/proofs/3.png",
    "comment": "Screenshot of finished deck",
    "creator_name": "Bob Lee",
    "created_at": "2026-06-09T14:10:00Z"
  }
]
```

---

### GET `/api/v1/mobile/missions/{mission_id}/subtasks`

**Response 200**
```json
[
  {
    "id": 92,
    "source": "management",
    "mission_id": 47,
    "title": "Gather metrics",
    "description": "Pull from analytics dashboard",
    "status": "in_progress",
    "is_done": false,
    "order": 1,
    "deadline": "2026-06-05",
    "finish_date": null,
    "creator_name": "Alice Doe",
    "executor_name": "Bob Lee",
    "created_at": "2026-05-20T09:18:00Z"
  }
]
```

---

## 6. Mission events — write

All write endpoints below: caller must be creator / executor / reviewer of
the mission. `404` if the mission doesn't exist in your home DB.

### POST `/api/v1/mobile/missions/{mission_id}/comments`

**Request**
```json
{
  "text": "Pushed v2 — feedback welcome",
  "attachment_path": "/uploads/comments/14.pdf"
}
```

`attachment_path` is optional (just a comment text is fine).

**Response 201** — single `MobileCommentOut`.

---

### POST `/api/v1/mobile/missions/{mission_id}/attachments`

**Request**
```json
{
  "file_path": "/uploads/missions/47/spec.pdf",
  "note": "Original brief"
}
```

The file should already be uploaded to your storage (S3, local, etc.); this
endpoint only records the metadata.

**Response 201** — single `MobileAttachmentOut`.

---

### POST `/api/v1/mobile/missions/{mission_id}/proofs`

**Request**
```json
{
  "file_path": "/uploads/proofs/3.png",
  "comment": "Final deck screenshot"
}
```

**Response 201** — single `MobileProofOut`.

---

### POST `/api/v1/mobile/missions/{mission_id}/subtasks`

**Request**
```json
{
  "title": "Outline talking points",
  "description": "3 bullets per slide",
  "deadline": "2026-06-07",
  "order": 2,
  "executor_id": 18
}
```

`executor_id` is honored on management subtasks; ignored on gennis/turon
(their schemas don't carry per-subtask executors).

**Response 201** — single `MobileSubtaskOut`.

---

## 7. Subtasks

### GET `/api/v1/mobile/subtasks/{subtask_id}`

**Response 200** — single `MobileSubtaskOut`.

---

### PATCH `/api/v1/mobile/subtasks/{subtask_id}`

Partial update. Caller must be a participant on the parent mission.

**Request** — any subset:
```json
{
  "title": "Outline talking points — v2",
  "is_done": true,
  "finish_date": "2026-06-06"
}
```

Setting `is_done: true` auto-fills `finish_date` with today if you omit it.

**Response 200** — updated subtask.

**Errors:** `400` empty payload, `403`, `404`.

---

### DELETE `/api/v1/mobile/subtasks/{subtask_id}`

Soft delete on management; hard delete on gennis/turon. Caller must be a
participant on the parent mission.

**Response 204** — empty.

---

## 8. Subtask events

Same shapes and rules as mission events, just scoped to a subtask. Caller
must be a participant on the **parent mission**.

### GET `/api/v1/mobile/subtasks/{subtask_id}/comments`

Returns `MobileCommentOut[]`.

### GET `/api/v1/mobile/subtasks/{subtask_id}/attachments`

Returns `MobileAttachmentOut[]`.

### GET `/api/v1/mobile/subtasks/{subtask_id}/proofs`

Returns `MobileProofOut[]`.

### POST `/api/v1/mobile/subtasks/{subtask_id}/comments`

Same payload as mission comment.

**Request**
```json
{ "text": "Done with bullets — moving on", "attachment_path": null }
```

**Response 201** — `MobileCommentOut`.

### POST `/api/v1/mobile/subtasks/{subtask_id}/attachments`

**Request**
```json
{ "file_path": "/uploads/subtasks/92/bullets.txt", "note": "Notes file" }
```

**Response 201** — `MobileAttachmentOut`.

### POST `/api/v1/mobile/subtasks/{subtask_id}/proofs`

**Request**
```json
{ "file_path": "/uploads/proofs/sub-92.png", "comment": "Done" }
```

**Response 201** — `MobileProofOut`.

---

## End-to-end flow examples

### A. Gennis user creates and completes a mission

```http
POST /api/v1/mobile/auth/login
{ "system": "gennis", "username": "bob", "password": "..." }
→ { access_token, refresh_token, ... }

POST /api/v1/mobile/missions/
Authorization: Bearer <access>
{ "title": "Order new whiteboard", "executor_id": 27, "deadline": "2026-06-15" }
→ 201 { id: 88, source: "gennis", status: "pending", ... }

PATCH /api/v1/mobile/missions/88/status
{ "status": "in_progress" }
→ 200 updated

POST /api/v1/mobile/missions/88/proofs
{ "file_path": "/uploads/proofs/88.jpg", "comment": "Whiteboard installed" }
→ 201

POST /api/v1/mobile/missions/88/complete
{ "finish_date": "2026-06-14" }
→ 200 status: "completed"
```

### B. Linking Telegram for notifications

```http
POST /api/v1/mobile/telegram/generate-link-code
→ { code: "Xa3kP9bQ", deep_link: "https://t.me/<bot>?start=Xa3kP9bQ" }

# User opens deep_link in Telegram and sends /start to the bot

GET /api/v1/mobile/telegram/status
→ { "linked": true, "telegram_id": 123456789 }
```

Once linked, every mission event that mentions you (assigned, status
changed, completed, etc.) is delivered to your Telegram chat.

---

## Notes for mobile devs

- **Token lifetime:** access token expires in `expires_in` seconds; call
  `/auth/refresh` before then with the stored `refresh_token`. The refresh
  endpoint rotates both tokens.
- **Pagination:** list endpoints accept `limit` + `offset`. `total` in the
  response is the unbounded count, not the page size.
- **Idempotency:** all writes use plain POST/PATCH — no idempotency-key
  header right now. Retry-on-network-error will create duplicates.
- **File uploads:** this surface does NOT handle file uploads. Upload to
  your storage (S3 / nginx / whatever) first, then POST the path here.
- **Cross-system reads:** you only ever see your home system's missions.
  Management-originated missions synced into gennis/turon DBs are visible
  via the home-DB query.
- **Permissions in one line:** you must be the creator, executor, or
  reviewer of a mission to mutate it or post events on it. Plus: approve
  → reviewer/creator; complete → executor; redirect → creator.
