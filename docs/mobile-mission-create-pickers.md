# Mobile mission-create pickers — frontend integration guide

Three new GET endpoints and one breaking change to the mission-create POST,
all under `/api/v1/mobile/`. These exist so the mobile mission-create form
can replace the manual "type a user ID" inputs with proper, permission-aware
pickers that mirror the rules the web client already enforces.

All endpoints require `Authorization: Bearer <access_token>` from
`POST /mobile/auth/login`. The JWT carries `system` + `external_id`, so the
server scopes results to the caller's home DB automatically — there are no
`?system=` query params on these routes.

---

## What changed

| Change                                                | Type       |
|-------------------------------------------------------|------------|
| `POST /api/v1/mobile/missions/` — `deadline` required | **breaking** |
| `GET /api/v1/mobile/users/eligible-executors`         | new        |
| `GET /api/v1/mobile/projects`                         | new        |
| `GET /api/v1/mobile/sections`                         | new        |

---

## Recommended UI flow

```
1. Auth (already in place)
        │
        ▼
2. Decide scope (management callers only)
        │
        ├─ Personal / line-management → skip to step 4
        │
        ├─ Project-scoped:
        │     GET /mobile/projects
        │     → user picks one with role="manager"
        │
        └─ Section-scoped:
              GET /mobile/sections
              → user picks one with role="leader"
        │
        ▼
3. Load eligible executors
        GET /mobile/users/eligible-executors
            ?channel=project|service_request|line_management
            &project_id=<id>      (if project scope)
            &section_id=<id>      (if section scope)
        │
        ▼
4. User picks executor + (optional) reviewer from the list
        │
        ▼
5. POST /mobile/missions
        { title, deadline, executor_id, reviewer_id?, kpi_weight?, ... }
```

Gennis / Turon callers can skip steps 2 directly to step 3 — they get
an unfiltered list of active users from their own DB.

---

## 1. `POST /api/v1/mobile/missions/` — `deadline` now required

**Breaking change.** Before this release `deadline` was `Optional[date]`.
Both `mission.deadline` (management) and `tasks_mission.deadline` (Turon)
are `NOT NULL` at the DB level, so requests without a deadline were crashing
at commit with `IntegrityError`. The schema now rejects them at validation
time instead.

**Request — was**
```json
{
  "title": "string",
  "executor_id": 1,
  "deadline": null
}
```

**Request — now**
```json
{
  "title": "string",
  "executor_id": 1,
  "deadline": "2026-06-15"
}
```

**Failure** — missing or null deadline now returns `422`:
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "deadline"],
      "msg": "Field required"
    }
  ]
}
```

Mobile UI: the "Muddat" (deadline) field must be mandatory on the form,
not optional. There is no longer a "default to undefined" branch on the
server.

---

## 2. `GET /api/v1/mobile/users/eligible-executors`

The users the caller is allowed to assign a mission to.

### Query params

| Param        | Type    | Required | Applies to     | Notes |
|--------------|---------|----------|----------------|-------|
| `channel`    | string  | no       | management     | `line_management` (default), `project`, or `service_request`. `service_request` returns every active management user; useful for cross-department asks. |
| `project_id` | int     | no       | management     | Required when the caller's role is `manager` and they're creating a project mission. Server checks the caller actually manages this project. |
| `section_id` | int     | no       | management     | Required when the caller's role is `manager` and they're creating a section mission. Server checks the caller actually leads this section. |

Gennis / Turon callers should not send any of these — they're ignored.

### Response (200)

```json
[
  {
    "id": 423,
    "system": "management",
    "name": "Alice",
    "surname": "Karimova",
    "role": "team_lead"
  },
  {
    "id": 424,
    "system": "management",
    "name": "Bobur",
    "surname": "Tursunov",
    "role": "specialist"
  }
]
```

| Field     | Type        | Notes |
|-----------|-------------|-------|
| `id`      | int         | The user's id in the caller's home system. Pass this back as `executor_id` / `reviewer_id` on `POST /mobile/missions`. |
| `system`  | enum        | `"management" \| "gennis" \| "turon"`. Always matches the caller's home system. |
| `name`    | string?     | Given name. May be null on Gennis/Turon. |
| `surname` | string?     | Family name. May be null. |
| `role`    | string?     | Management → role enum string (`owner`, `manager`, `team_lead`, …). Gennis → the `roles.role` text column. Turon → the name of the first associated `auth_group`. May be null when no group is assigned. |

### Behaviour per system

| Caller system | List composition |
|---------------|------------------|
| **management** | Reuses the same `_eligible_executors()` rules the web client uses. **Owner** → every active user not already attached to a project/section. **Manager** + `project_id` → members of that project (only if the caller manages it); same for `section_id`. **Any other role** → users whose role is in `ROLE_CAN_ASSIGN[creator.role]`, plus the caller themself. `channel=service_request` short-circuits to "every active user". |
| **gennis**     | All active users from the Gennis `users` table joined with `roles.role`. No hierarchy filter — Gennis doesn't model one. |
| **turon**      | All active users from `user_customuser` (`is_active = true`). The `role` is the alphabetical-first associated `auth_group.name`. |

### Empty list

A management manager that hasn't selected a `project_id` / `section_id` will
get a single-entry list (themself). Mobile UI should treat that as "you need
to pick a project or section first, OR you're only allowed to assign to
yourself."

---

## 3. `GET /api/v1/mobile/projects`

The projects the caller manages or belongs to. Used to populate the
project-scope picker before fetching executors.

### Response (200)

```json
[
  {
    "id": 12,
    "name": "Q3 Onboarding",
    "description": "Cross-functional onboarding overhaul",
    "role": "manager"
  },
  {
    "id": 18,
    "name": "Brand refresh",
    "description": null,
    "role": "member"
  }
]
```

| Field         | Type    | Notes |
|---------------|---------|-------|
| `id`          | int     | Pass back as `project_id` to `/eligible-executors`. |
| `name`        | string  | |
| `description` | string? | |
| `role`        | enum    | `"manager"` (caller manages the project — can assign missions here) or `"member"` (caller only participates). |

**Ordering**: `manager` rows come first, then `member` rows. Within each
group, sorted by `name` ASC. The mobile UI can render two sections labeled
"You manage" and "You belong to" without reshuffling on the client.

### Behaviour per system

| Caller system | Response |
|---------------|----------|
| **management** | Projects where `Project.manager_id == external_id` OR the caller is a `ProjectMember`. Deleted projects excluded. |
| **gennis**     | `[]` — Gennis doesn't model projects. |
| **turon**      | `[]` — Turon doesn't model projects. |

Empty list is **not** an error. Mobile UI should hide the project picker
entirely when this returns `[]`.

---

## 4. `GET /api/v1/mobile/sections`

The sections the caller leads or belongs to.

### Response (200)

```json
[
  {
    "id": 4,
    "name": "Marketing",
    "role": "leader"
  },
  {
    "id": 7,
    "name": "Operations",
    "role": "member"
  }
]
```

| Field   | Type   | Notes |
|---------|--------|-------|
| `id`    | int    | Pass back as `section_id` to `/eligible-executors`. |
| `name`  | string | |
| `role`  | enum   | `"leader"` or `"member"`. Only leaders can assign within their section. |

**Ordering**: leaders first, then members; alphabetical within each.

### Behaviour per system

| Caller system | Response |
|---------------|----------|
| **management** | Sections where `Section.leader_id == external_id` OR the caller is a `SectionMember`. Deleted sections excluded. |
| **gennis**     | `[]` |
| **turon**      | `[]` |

---

## Errors

| Status | When                                                       |
|--------|------------------------------------------------------------|
| 401    | Missing / invalid / expired access token                   |
| 404    | `eligible-executors` only, management caller: creator row not found in `user` table (token references a user that no longer exists) |
| 422    | `POST /missions/` — `deadline` missing or wrong type       |

All other endpoints return `200` with `[]` rather than an error when the
caller's scope is empty.

---

## Example: end-to-end mission create (management manager)

```http
POST /api/v1/mobile/auth/login
{ "system": "management", "username": "alice@…", "password": "…" }
→ 200 { access_token, … }

GET /api/v1/mobile/projects                       Bearer ...
→ 200 [ { id: 12, name: "Q3 Onboarding", role: "manager" }, … ]

GET /api/v1/mobile/users/eligible-executors?channel=project&project_id=12
                                                  Bearer ...
→ 200 [ { id: 423, name: "Alice", role: "team_lead" }, … ]

POST /api/v1/mobile/missions/                     Bearer ...
{
  "title": "Draft onboarding checklist",
  "description": "Cover all four locales",
  "executor_id": 423,
  "reviewer_id": 412,
  "deadline": "2026-06-30",
  "kpi_weight": 20
}
→ 201 { id: 211, source: "management", status: "pending", … }
```

## Example: end-to-end mission create (Turon caller)

```http
GET /api/v1/mobile/projects                       Bearer ...
→ 200 []                          # Turon has no projects, hide picker

GET /api/v1/mobile/users/eligible-executors       Bearer ...
→ 200 [ { id: 6, system: "turon", name: "admin", role: null }, … ]

POST /api/v1/mobile/missions/                     Bearer ...
{
  "title": "Tekshiruv",
  "executor_id": 6,
  "deadline": "2026-06-15"
}
→ 201 { id: 212, source: "turon", … }
```
