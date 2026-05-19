# Mission Subtask sub-records — frontend integration guide

All routes live under
`/api/v1/missions/{mission_id}/subtasks/{subtask_id}/…` and mirror the
mission-level comment/attachment/proof endpoints — a subtask is now a
self-contained unit with its own discussion thread, attached files, and
completion proofs.

## What changed on `MissionSubtask`

The subtask model has been extended to match the shape of a `Mission`. New
columns:

| Column          | Type      | Notes |
|-----------------|-----------|-------|
| `creator_id`    | bigint    | FK → `user.id`. Set automatically from the `creator_id` query param on POST. |
| `reviewer_id`   | bigint    | FK → `user.id`. Optional. |
| `description`   | text      | Long-form description, same role as on mission. |
| `status`        | varchar   | Same enum vocabulary as mission (`not_started`, `in_progress`, `blocked`, `completed`, `approved`, `declined`, `recheck`). Defaults to `not_started`. |
| `start_date`    | date      | Defaults to today on the server. |
| `deadline`      | date      | Optional. |
| `finish_date`   | date      | Set when the subtask is closed. |
| `created_at`    | datetime  | Server-set on insert. |
| `updated_at`    | datetime  | Server-set on update. |

The original `executor_id`, `title`, `is_done`, `order`, `deleted` fields are
unchanged.

Three relationships were added: `comments`, `attachments`, `proofs`. They
behave identically to the mission-level counterparts.

### MissionSubtaskOut (new shape)

```jsonc
{
  "id": 42,
  "mission_id": 17,
  "creator_id": 3,
  "executor_id": 5,
  "reviewer_id": null,
  "creator":  { "id": 3, "name": "Aziza", "surname": "K." },
  "executor": { "id": 5, "name": "Bobur", "surname": "M." },
  "reviewer": null,
  "title": "Prepare draft",
  "description": "Outline the proposal in 1 page",
  "is_done": false,
  "order": 1,
  "status": "in_progress",
  "start_date": "2026-05-19",
  "deadline":   "2026-05-22",
  "finish_date": null,
  "created_at": "2026-05-19T08:11:42",
  "updated_at": "2026-05-19T09:02:10"
}
```

### Create / Update subtask payloads

`POST /api/v1/missions/{mission_id}/subtasks/?creator_id=<id>`

```jsonc
{
  "title": "Prepare draft",        // required
  "description": "...",            // optional
  "order": 1,                      // optional, default 0
  "status": "not_started",         // optional
  "creator_id": 3,                 // optional in body; falls back to query param
  "executor_id": 5,                // optional
  "reviewer_id": null,             // optional
  "deadline": "2026-05-22"         // optional
}
```

`PATCH /api/v1/missions/{mission_id}/subtasks/{subtask_id}`

Any field above (plus `is_done` and `finish_date`) may be sent. Omitted
fields are left untouched.

---

## Endpoints (sub-records)

All endpoints below are scoped to a single subtask and require that both
the mission and the subtask exist (and are not soft-deleted). They return
`404` otherwise.

Each successful create / update / delete is mirrored to the linked Gennis
and/or Turon row when the parent mission has a `gennis_executor_id` /
`turon_executor_id`. Participants of the parent mission and the subtask
(`creator`, `executor`, `reviewer` on both sides) receive a Telegram push
when a comment / attachment / proof is added.

| Endpoint                                                                                       | Section |
|------------------------------------------------------------------------------------------------|---------|
| `POST /missions/{mid}/subtasks/{sid}/comments/`                                                | [#comments](#subtask-comments) |
| `GET  /missions/{mid}/subtasks/{sid}/comments/`                                                | [#comments](#subtask-comments) |
| `PATCH /missions/{mid}/subtasks/{sid}/comments/{cid}`                                          | [#comments](#subtask-comments) |
| `DELETE /missions/{mid}/subtasks/{sid}/comments/{cid}`                                         | [#comments](#subtask-comments) |
| `POST /missions/{mid}/subtasks/{sid}/attachments/`                                             | [#attachments](#subtask-attachments) |
| `GET  /missions/{mid}/subtasks/{sid}/attachments/`                                             | [#attachments](#subtask-attachments) |
| `PATCH /missions/{mid}/subtasks/{sid}/attachments/{aid}`                                       | [#attachments](#subtask-attachments) |
| `DELETE /missions/{mid}/subtasks/{sid}/attachments/{aid}`                                      | [#attachments](#subtask-attachments) |
| `POST /missions/{mid}/subtasks/{sid}/proofs/`                                                  | [#proofs](#subtask-proofs) |
| `GET  /missions/{mid}/subtasks/{sid}/proofs/`                                                  | [#proofs](#subtask-proofs) |
| `PATCH /missions/{mid}/subtasks/{sid}/proofs/{pid}`                                            | [#proofs](#subtask-proofs) |
| `DELETE /missions/{mid}/subtasks/{sid}/proofs/{pid}`                                           | [#proofs](#subtask-proofs) |

> All file URLs returned by the API are **absolute** — they are joined with
> `BASE_URL` server-side. The frontend can use them directly in
> `<img src>`, `<a href>`, etc.

---

## Subtask Comments

Threaded discussion under a single subtask. Each comment may carry **one**
optional file attachment (image, doc, etc.).

### POST — add comment

`POST /api/v1/missions/{mission_id}/subtasks/{subtask_id}/comments/`

**Content-Type:** `multipart/form-data`

| Field       | Required | Type        | Notes |
|-------------|----------|-------------|-------|
| `user_id`   | yes      | int         | Author. Used for Telegram notifications + `user` join in the response. |
| `text`      | yes      | string      | The comment body. |
| `attachment`| no       | file        | Optional file. Stored under `uploads/mission_subtask_comments/`. |

**Response 201** — `MissionSubtaskCommentOut`

```jsonc
{
  "id": 11,
  "subtask_id": 42,
  "user_id": 3,
  "user": { "id": 3, "name": "Aziza", "surname": "K." },
  "creator_name": "Aziza K.",
  "text": "First pass attached.",
  "attachment": "https://api.example.com/uploads/mission_subtask_comments/<uuid>.pdf",
  "created_at": "2026-05-19T10:21:33"
}
```

### GET — list comments

`GET /api/v1/missions/{mission_id}/subtasks/{subtask_id}/comments/`

Returns all non-deleted comments for the subtask, ordered by `created_at`
ascending. Same shape as POST.

### PATCH — edit comment

`PATCH /api/v1/missions/{mission_id}/subtasks/{subtask_id}/comments/{comment_id}`

**Content-Type:** `multipart/form-data` (both fields optional)

| Field       | Type   | Notes |
|-------------|--------|-------|
| `text`      | string | Overwrite body. |
| `attachment`| file   | Replace the attachment. |

### DELETE — soft-delete

`DELETE /api/v1/missions/{mission_id}/subtasks/{subtask_id}/comments/{comment_id}`

204 No Content. Removed from list responses and from the synced Gennis /
Turon row.

---

## Subtask Attachments

Files attached **to the subtask itself** (specs, designs, mock-ups, etc.).
Different from comment attachments — these don't belong to any one
comment.

### POST — upload attachment

`POST /api/v1/missions/{mission_id}/subtasks/{subtask_id}/attachments/`

**Content-Type:** `multipart/form-data`

| Field        | Required | Type   | Notes |
|--------------|----------|--------|-------|
| `file`       | yes      | file   | The file to attach. Stored under `uploads/mission_subtask_attachments/`. |
| `note`       | no       | string | Short description (≤ 255 chars). |
| `creator_id` | yes      | int    | Uploader. Drives `creator_name` and Telegram notifications. |

**Response 201** — `MissionSubtaskAttachmentOut`

```jsonc
{
  "id": 7,
  "subtask_id": 42,
  "file": "https://api.example.com/uploads/mission_subtask_attachments/<uuid>.png",
  "uploaded_at": "2026-05-19T10:30:00",
  "note": "Design mock v1",
  "creator_name": "Aziza K."
}
```

### GET — list attachments

`GET /api/v1/missions/{mission_id}/subtasks/{subtask_id}/attachments/`

Returns all non-deleted attachments for the subtask.

### PATCH — edit attachment

`PATCH /api/v1/missions/{mission_id}/subtasks/{subtask_id}/attachments/{attachment_id}`

**Content-Type:** `multipart/form-data` (both fields optional)

| Field  | Type   | Notes |
|--------|--------|-------|
| `file` | file   | Replace the stored file. |
| `note` | string | Replace the note. |

### DELETE — soft-delete

`DELETE /api/v1/missions/{mission_id}/subtasks/{subtask_id}/attachments/{attachment_id}`

204 No Content.

---

## Subtask Proofs

Proof-of-completion uploads — typically a screenshot or document showing
that the subtask is done. Distinct from generic attachments: proofs
signal "I finished this".

### POST — upload proof

`POST /api/v1/missions/{mission_id}/subtasks/{subtask_id}/proofs/`

**Content-Type:** `multipart/form-data`

| Field        | Required | Type   | Notes |
|--------------|----------|--------|-------|
| `file`       | yes      | file   | Proof file. Stored under `uploads/mission_subtask_proofs/`. |
| `comment`    | no       | string | Optional caption (≤ 255 chars). |
| `creator_id` | yes      | int    | Uploader. Drives `creator_name` and Telegram notifications. |

**Response 201** — `MissionSubtaskProofOut`

```jsonc
{
  "id": 4,
  "subtask_id": 42,
  "file": "https://api.example.com/uploads/mission_subtask_proofs/<uuid>.png",
  "comment": "Screen of final draft",
  "creator_name": "Bobur M.",
  "created_at": "2026-05-19T11:14:09"
}
```

### GET — list proofs

`GET /api/v1/missions/{mission_id}/subtasks/{subtask_id}/proofs/`

### PATCH — edit proof

`PATCH /api/v1/missions/{mission_id}/subtasks/{subtask_id}/proofs/{proof_id}`

**Content-Type:** `multipart/form-data`

| Field     | Type   | Notes |
|-----------|--------|-------|
| `file`    | file   | Replace the proof file. |
| `comment` | string | Replace the caption. |

### DELETE — soft-delete

`DELETE /api/v1/missions/{mission_id}/subtasks/{subtask_id}/proofs/{proof_id}`

204 No Content.

---

## Notifications

When a comment / attachment / proof is added under a subtask, the API
sends Telegram notifications (via Celery) to the union of:

- mission `creator_id`, `executor_id`, `reviewer_id`
- subtask `creator_id`, `executor_id`, `reviewer_id`

minus the actor (`user_id` / `creator_id` of the request) and minus any
`null`s. Users without a `telegram_id` are silently skipped.

Title format used in the Telegram message: `<mission.title> / <subtask.title>`
— so recipients see both contexts.

Template functions reused from the mission level:

- `tpl_comment_added(name, title, sender, text)`
- `tpl_attachment_added(name, title, sender)`
- `tpl_proof_added(name, title, sender, comment)`

---

## Cross-system sync

Each sub-record is mirrored to the parent mission's external row:

| Origin (management table)         | Gennis table                    | Turon table                          |
|-----------------------------------|---------------------------------|--------------------------------------|
| `mission_subtask_comment`         | `mission_subtask_comments`      | `tasks_missionsubtaskcomment`        |
| `mission_subtask_attachment`      | `mission_subtask_attachments`   | `tasks_missionsubtaskattachment`     |
| `mission_subtask_proof`           | `mission_subtask_proofs`        | `tasks_missionsubtaskproof`          |

Sync rules:

- Only runs when `mission.gennis_executor_id` / `mission.turon_executor_id`
  is set (i.e. the parent mission is mirrored).
- Only runs when the parent `mission_subtasks` row has already been mirrored
  (linked by `management_id`).
- Soft-delete on the management side hard-deletes the external row.
- File fields are stored with a **full absolute URL** on the external side
  (so Gennis/Turon frontends can render them without knowing about the
  management host).

---

## Frontend example — React Query

```ts
// List comments
const { data: comments } = useQuery({
  queryKey: ["subtask-comments", missionId, subtaskId],
  queryFn: () =>
    api.get(`/missions/${missionId}/subtasks/${subtaskId}/comments/`).then(r => r.data),
});

// Add a comment with optional file
async function addComment(missionId: number, subtaskId: number, userId: number, text: string, file?: File) {
  const fd = new FormData();
  fd.append("user_id", String(userId));
  fd.append("text", text);
  if (file) fd.append("attachment", file);
  return api.post(`/missions/${missionId}/subtasks/${subtaskId}/comments/`, fd).then(r => r.data);
}

// Upload a proof
async function addProof(missionId: number, subtaskId: number, creatorId: number, file: File, caption?: string) {
  const fd = new FormData();
  fd.append("creator_id", String(creatorId));
  fd.append("file", file);
  if (caption) fd.append("comment", caption);
  return api.post(`/missions/${missionId}/subtasks/${subtaskId}/proofs/`, fd).then(r => r.data);
}
```

## Status / error reference

| HTTP code | Meaning                                  |
|-----------|------------------------------------------|
| `201`     | Created — record persisted, sync started |
| `200`     | Updated / listed                          |
| `204`     | Soft-deleted                              |
| `404`     | Mission, subtask, or sub-record not found (or already soft-deleted) |
| `422`     | Validation failure (missing form field, wrong content-type) |
| `500`     | Server error — check FastAPI logs        |

---

## Statistics — new subtask fields

The three existing mission-statistics endpoints now return parallel
subtask metrics. Mission-level fields are unchanged; the additions are
described below.

### `GET /api/v1/missions/external/stats`

Adds a `subtasks` block to each system. Same `location_id` / `branch_id`
filter is applied via the parent mission join (so subtasks under a
filtered-out mission are excluded).

```jsonc
{
  "gennis": {
    "total": 142,
    "by_status": { /* unchanged */ },
    "subtasks": {
      "total": 380,
      "done": 215,
      "pending": 165,
      "by_status": {
        "not_started": 90,
        "in_progress": 65,
        "blocked": 10,
        "completed": 180,
        "approved": 35,
        "declined": 0,
        "recheck": 0
      }
    }
  },
  "turon": { "...": "same shape" }
}
```

### `GET /api/v1/missions/stats/user-performance`

Each per-user object gains a `subtasks` block, and `overall` does too.
Subtasks are scoped to the same `from_date` / `to_date` deadline window
as missions. Subtasks without a deadline are included to avoid hiding
parent-aligned work.

```jsonc
{
  "users": [
    {
      "user_id": 3,
      "name": "Aziza", "surname": "K.", "role": "team_lead",
      "total": 12, "finished": 9, "approved": 7, "...": "...",
      "subtasks": {
        "total": 24,
        "done": 18,
        "pending": 6,
        "approved": 14,
        "done_percentage": 75.0,
        "pending_percentage": 25.0,
        "on_time": 15,
        "late": 3,
        "on_time_percentage_of_done": 83.33,
        "late_percentage_of_done": 16.67
      }
    }
  ],
  "overall": {
    "total": 50, "finished": 32, "...": "...",
    "subtasks": { "...": "same shape, aggregated" }
  }
}
```

- `done` = `is_done == true` OR `status in (completed, approved)`
- `approved` = `status == "approved"`
- `on_time` / `late` require both `finish_date` and `deadline` to be set;
  rows missing either are dropped from the on-time bucket but still
  counted in `done`.

### `GET /api/v1/missions/stats/managers`

Each manager row gains four subtask counters and three share/rate
percentages. `totals` and the sort order are also updated to include
subtask volume.

```jsonc
{
  "totals": {
    "created": 80, "reviewed": 95, "received": 110, "rejected": 5,
    "subtasks_created": 210,
    "subtasks_reviewed": 60,
    "subtasks_received": 240,
    "subtasks_done": 175
  },
  "managers": [
    {
      "id": 3, "name": "Aziza K.", "role": "team_lead",
      "created": 18, "reviewed": 22, "received": 14, "rejected": 1,
      "created_share_pct": 22.5, "...": "...",

      "subtasks_created":   42,
      "subtasks_reviewed":  12,
      "subtasks_received":  48,
      "subtasks_done":      36,

      "subtasks_created_share_pct":  20.0,
      "subtasks_received_share_pct": 20.0,
      "subtasks_done_rate_pct":      75.0
    }
  ]
}
```

- `subtasks_created` — subtasks where the manager is `creator_id`
- `subtasks_reviewed` — subtasks where the manager is `reviewer_id`
- `subtasks_received` — subtasks where the manager is `executor_id`
- `subtasks_done` — subset of `subtasks_received` that are `is_done` or
  `status in (completed, approved)`
- `subtasks_done_rate_pct` — `subtasks_done / subtasks_received`
- Subtask rows are filtered by `created_at` within the same
  `[from_date, to_date]` window the endpoint already accepts for
  missions.
