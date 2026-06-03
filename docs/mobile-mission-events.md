# Mobile mission events: history, comments, attachments, proofs, subtasks

All routes live under the same base as the rest of the mobile API:

```
https://office.gennis.uz/api/v1/mobile/
```

Every endpoint requires the mobile JWT (`Authorization: Bearer <token>`) — the
same token used by `/auth/google` and `/missions/...`. The token's identity
(`system` = `management` / `gennis` / `turon`) decides which database is
written to and which `source` value the response carries.

The response envelope for every event type is *the same shape regardless of
caller's system* — so the mobile UI can render a single list view without
branching on `source`.

Source code: [`app/mobile/events.py`](../app/mobile/events.py). Schemas:
[`app/mobile/schemas.py`](../app/mobile/schemas.py).

---

## How routing by system works

For each request the server looks at the JWT claim `identity.system` and:

| `identity.system` | Writes / reads from           | `source` in response |
| ----------------- | ----------------------------- | -------------------- |
| `management`      | management Postgres (this app)| `"management"`       |
| `gennis`          | Gennis Flask DB               | `"gennis"`           |
| `turon`           | Turon Django DB               | `"turon"`            |

There is **no cross-system fan-out** — a mobile user from Gennis sees only
Gennis comments on a mission. This matches how mission lists already behave.

---

## Response envelopes (shared)

### `MobileHistoryEntry`

```json
{
  "id": 1234,
  "source": "management",
  "status": "in_progress",
  "note": "executor reassigned",
  "changed_by_name": "Begzod Akhmedov",
  "executor_name": "Aziz Karimov",
  "reviewer_name": "Diyora R.",
  "created_at": "2026-05-30T14:02:11Z"
}
```

> **Turon note:** Turon's `tasks_missionhistory` table has no `status` column,
> so `status` is always `null` for `source == "turon"` entries. Other fields
> behave normally.

### `MobileCommentOut`

```json
{
  "id": 88,
  "source": "gennis",
  "text": "shartnoma yangilandi",
  "user_id": 423,
  "user_name": "Aziz Karimov",
  "attachment_path": "/uploads/comments/2026/05/file.pdf",
  "created_at": "2026-05-30T14:02:11Z"
}
```

### `MobileAttachmentOut`

```json
{
  "id": 17,
  "source": "turon",
  "file_path": "/uploads/missions/2026/05/spec.pdf",
  "note": "v3 with translator notes",
  "creator_name": "Diyora R.",
  "uploaded_at": "2026-05-30T14:02:11Z"
}
```

### `MobileProofOut`

```json
{
  "id": 9,
  "source": "management",
  "file_path": "/uploads/proofs/2026/05/signed.pdf",
  "comment": "client signed copy",
  "creator_name": "Aziz Karimov",
  "created_at": "2026-05-30T14:02:11Z"
}
```

### `MobileSubtaskOut`

```json
{
  "id": 42,
  "source": "management",
  "mission_id": 210,
  "title": "Translate intro section",
  "description": null,
  "status": "in_progress",
  "is_done": false,
  "order": 0,
  "deadline": "2026-06-10",
  "finish_date": null,
  "creator_name": "Begzod Akhmedov",
  "executor_name": "Aziz Karimov",
  "created_at": "2026-05-28T09:15:00Z"
}
```

---

## Mission-level routes

### `GET /missions/{mission_id}/history`

Returns the ordered audit trail for a mission. Read-only. There is **no**
`POST` — history rows are generated server-side on status changes,
approvals, redirects, and completions.

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/missions/{mission_id}/history` |
| Response | `MobileHistoryEntry[]` ordered by `created_at ASC` |

Per-system behaviour:

| Caller       | Source table                                  | Notes |
| ------------ | --------------------------------------------- | ----- |
| management   | `mission_history` (management)                | full status field |
| gennis       | `mission_history` (Gennis Flask DB)           | full status field |
| turon        | `tasks_missionhistory` (Turon Django DB)      | `status` is always `null` (column doesn't exist in Turon yet) |

### `GET /missions/{mission_id}/comments`

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/missions/{mission_id}/comments` |
| Response | `MobileCommentOut[]` ordered by `created_at ASC` |

### `POST /missions/{mission_id}/comments`

| | |
| --- | --- |
| Method | `POST` |
| Path | `/api/v1/mobile/missions/{mission_id}/comments` |
| Body | `MobileCommentCreate` |
| Response | `201 Created` + `MobileCommentOut` |

Body:

```json
{
  "text": "shartnoma yangilandi",
  "attachment_path": "/uploads/comments/2026/05/file.pdf"
}
```

- `text` — required, min length 1.
- `attachment_path` — optional. The mobile client uploads the file via a
  separate upload endpoint and posts the resulting path here. The backend
  does not validate that the path exists.

The comment is written to the caller's system; `user_id` is filled from the
JWT.

### `GET /missions/{mission_id}/attachments`

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/missions/{mission_id}/attachments` |
| Response | `MobileAttachmentOut[]` |

### `POST /missions/{mission_id}/attachments`

| | |
| --- | --- |
| Method | `POST` |
| Path | `/api/v1/mobile/missions/{mission_id}/attachments` |
| Body | `MobileAttachmentCreate` |
| Response | `201 Created` + `MobileAttachmentOut` |

Body:

```json
{
  "file_path": "/uploads/missions/2026/05/spec.pdf",
  "note": "v3 with translator notes"
}
```

- `file_path` — required, min length 1.
- `note` — optional.

`creator_name` is auto-filled from the caller's profile.

### `GET /missions/{mission_id}/proofs`

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/missions/{mission_id}/proofs` |
| Response | `MobileProofOut[]` |

### `POST /missions/{mission_id}/proofs`

| | |
| --- | --- |
| Method | `POST` |
| Path | `/api/v1/mobile/missions/{mission_id}/proofs` |
| Body | `MobileProofCreate` |
| Response | `201 Created` + `MobileProofOut` |

Body:

```json
{
  "file_path": "/uploads/proofs/2026/05/signed.pdf",
  "comment": "client signed copy"
}
```

---

## Subtasks

A subtask is a checklist item under a mission. It has its own lifecycle
(`status`, `is_done`, `deadline`, `finish_date`) and its own comment /
attachment / proof streams. Subtasks live in the same DB as their parent
mission — Turon subtasks in `tasks_missionsubtask`, etc.

### `GET /missions/{mission_id}/subtasks`

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/missions/{mission_id}/subtasks` |
| Response | `MobileSubtaskOut[]` ordered by `order ASC, id ASC` |

### `GET /subtasks/{subtask_id}`

Detail view; useful when navigating from a notification deep-link.

| | |
| --- | --- |
| Method | `GET` |
| Path | `/api/v1/mobile/subtasks/{subtask_id}` |
| Response | `MobileSubtaskOut` |
| Errors | `404` if missing or soft-deleted |

### `POST /missions/{mission_id}/subtasks`

| | |
| --- | --- |
| Method | `POST` |
| Path | `/api/v1/mobile/missions/{mission_id}/subtasks` |
| Body | `MobileSubtaskCreate` |
| Response | `201 Created` + `MobileSubtaskOut` |

Body:

```json
{
  "title": "Translate intro section",
  "description": "Pages 1–4 only",
  "deadline": "2026-06-10",
  "order": 0,
  "executor_id": 423
}
```

- `title` — required, min length 1.
- `deadline` — optional (subtasks do not enforce NOT NULL like the parent
  mission's deadline).
- `executor_id` — id in the **caller's** system. Pass `null` to leave
  unassigned.

### `PATCH /subtasks/{subtask_id}`

Partial update. Any field omitted is left unchanged.

| | |
| --- | --- |
| Method | `PATCH` |
| Path | `/api/v1/mobile/subtasks/{subtask_id}` |
| Body | `MobileSubtaskUpdate` |
| Response | `MobileSubtaskOut` |

Body (all fields optional):

```json
{
  "title": "...",
  "description": "...",
  "status": "in_progress",
  "is_done": true,
  "order": 1,
  "deadline": "2026-06-15",
  "finish_date": "2026-06-09",
  "executor_id": 423
}
```

Transition behaviour matches the web subtask API: when the subtask first
becomes `is_done == true` (or `status` flips to `completed`/`approved`),
`finish_date` is auto-set to today if it was `null`.

### `DELETE /subtasks/{subtask_id}`

Soft-delete. Returns `204` with no body.

---

## Subtask events (comments / attachments / proofs)

Each route below works exactly like the mission-level counterpart, except
the URL is scoped to a subtask and the writes land in
`mission_subtask_comments` / `_attachments` / `_proofs` (or the equivalent
Gennis / Turon child table).

| Method | Path | Body | Response |
| ------ | ---- | ---- | -------- |
| `GET`  | `/api/v1/mobile/subtasks/{subtask_id}/comments`     | — | `MobileCommentOut[]` |
| `POST` | `/api/v1/mobile/subtasks/{subtask_id}/comments`     | `MobileCommentCreate` | `201` + `MobileCommentOut` |
| `GET`  | `/api/v1/mobile/subtasks/{subtask_id}/attachments`  | — | `MobileAttachmentOut[]` |
| `POST` | `/api/v1/mobile/subtasks/{subtask_id}/attachments`  | `MobileAttachmentCreate` | `201` + `MobileAttachmentOut` |
| `GET`  | `/api/v1/mobile/subtasks/{subtask_id}/proofs`       | — | `MobileProofOut[]` |
| `POST` | `/api/v1/mobile/subtasks/{subtask_id}/proofs`       | `MobileProofCreate` | `201` + `MobileProofOut` |

All POSTs validate that the subtask belongs to the caller's system before
writing — a Turon user cannot post into a management subtask.

---

## Error codes

| Status | When |
| ------ | ---- |
| `401`  | Missing / invalid / expired JWT |
| `404`  | Mission or subtask not found, or soft-deleted, or not in the caller's system |
| `422`  | Body fails schema validation (e.g. empty `text`, missing `file_path`) |
| `500`  | Server bug. Paste the journalctl line at the request timestamp into the chat — do **not** retry on a tight loop. |

---

## Quick request examples

Add a comment to mission 210 (caller = Gennis user):

```http
POST /api/v1/mobile/missions/210/comments HTTP/1.1
Host: office.gennis.uz
Authorization: Bearer <mobile-jwt>
Content-Type: application/json

{"text": "shartnoma yangilandi"}
```

Response:

```http
HTTP/1.1 201 Created
Content-Type: application/json

{
  "id": 88,
  "source": "gennis",
  "text": "shartnoma yangilandi",
  "user_id": 423,
  "user_name": "Aziz Karimov",
  "attachment_path": null,
  "created_at": "2026-06-03T08:15:00Z"
}
```

Create a subtask + upload a proof against it (caller = management user):

```http
POST /api/v1/mobile/missions/210/subtasks HTTP/1.1
Authorization: Bearer <mobile-jwt>
Content-Type: application/json

{"title": "Translate intro section", "deadline": "2026-06-10"}
```

→ `201` returns `{ "id": 42, ... }`

```http
POST /api/v1/mobile/subtasks/42/proofs HTTP/1.1
Authorization: Bearer <mobile-jwt>
Content-Type: application/json

{"file_path": "/uploads/proofs/2026/06/intro.pdf", "comment": "first pass"}
```

→ `201` returns the `MobileProofOut`.

---

## Related docs

- [`mobile-mission-create-pickers.md`](mobile-mission-create-pickers.md) —
  executor / project / section pickers feeding `POST /mobile/missions/`.
- [`mission-subtask-routes.md`](mission-subtask-routes.md) — the **web**
  `/api/v1/missions/...` counterparts of these routes (more fields, more
  validation; used by the management dashboard, not by mobile).
