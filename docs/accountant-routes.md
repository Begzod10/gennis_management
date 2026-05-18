# Buxgalteriya (Accountant) routes — frontend integration guide

All routes live under `/api/v1/accountant/*` and read from one of the two
external systems:

| `system` value | Source DB | Scope param |
|----------------|-----------|-------------|
| `gennis`       | Gennis (Flask) — read replica | `location_id` (Gennis `locations.id`) |
| `turon`        | Turon (Django) — read replica | `branch_id`   (Turon `branch_branch.id`) |

Always send **exactly one** of `location_id` / `branch_id`, matching the
chosen `system`. The server returns `400` if the wrong one is sent.

`month` / `year` default to the current month/year. All money amounts are
plain integers in soum (no decimals, no currency code).

Quick reference:

| Endpoint                                   | Screen        | Section |
|--------------------------------------------|---------------|---------|
| `GET /accountant/dashboard`                | Dashboard     | [#dashboard](#dashboard) |
| `GET /accountant/students`                 | O'quvchilar   | [#students](#students) |
| `GET /accountant/payments`                 | To'lovlar     | [#payments](#payments) |
| `GET /accountant/overheads`                | Xarajatlar    | [#overheads](#overheads) |
| `GET /accountant/salaries`                 | Ish haqi      | [#salaries](#salaries) |
| `GET /accountant/debts`                    | Qarzlar       | [#debts](#debts) |

---

## Dashboard

`GET /api/v1/accountant/dashboard`

KPIs + trend + recent payments for one location/branch.

### Query

| Param        | Required | Default | Description |
|--------------|----------|---------|-------------|
| `system`     | yes      | —       | `gennis` \| `turon` |
| `location_id`| gennis   | —       | Gennis location id |
| `branch_id`  | turon    | —       | Turon branch id |
| `date`       | no       | today   | Override "today" for testing (`YYYY-MM-DD`) |

### Response

```jsonc
{
  "system": "gennis",
  "scope_id": 4,
  "today": "2026-05-18",

  "today_payments": {
    "value": 12450000,
    "yesterday_value": 10550000,
    "delta_vs_yesterday_pct": 18.0    // null when yesterday was 0
  },
  "monthly_income": {
    "value": 142800000,
    "month": 5, "year": 2026,
    "month_label": "May 2026"
  },
  "debt": { "value": 38200000, "open_count": 27 },
  "today_expenses": {
    "value": 62400000,
    "salaries": 41000000,
    "overheads": 21400000
  },

  "trend": [                          // last 6 months, oldest first
    { "month": 12, "year": 2025, "label": "Dek", "income": 110000000 },
    // …
    { "month":  5, "year": 2026, "label": "May", "income": 142800000 }
  ],

  "recent_payments": [                // last 8 paid student payments
    { "id": 12345, "student_name": "Holmatov Bekzod",
      "amount": 850000, "channel": "Click",
      "date": "2026-05-18", "type": "Oy to'lovi", "status": "To'landi" }
  ]
}
```

### Notes

- `today_payments.value` counts only **real** student payments (`payment=True` in Gennis, `status=True` in Turon) — discounts are excluded.
- `today_expenses.salaries` sums daily salary transactions
  (`teachersalaries` + `assistent_salaries` + `staffsalaries` in Gennis;
  `teachers_teachersalarylist` + `user_usersalarylist` in Turon)
  joined to today's date.
- `today_expenses.overheads` adds the legacy `Overhead.created=today` total
  (Turon only) and any `OverheadTypeLogPayment` rows with `paid_date=today`.
- `trend.label` is the short Uzbek month abbreviation (`Yan`, `Fev`, …).

---

## Students

`GET /api/v1/accountant/students`

Table of students for one scope, with monthly fee, paid, remaining,
discount %, and a derived status.

### Query

| Param         | Required | Default | Description |
|---------------|----------|---------|-------------|
| `system`      | yes      | —       | `gennis` \| `turon` |
| `location_id` | gennis   | —       | |
| `branch_id`   | turon    | —       | |
| `month`,`year`| no       | today   | |
| `search`      | no       | —       | Name / surname / phone (Turon also matches phone) |
| `status`      | no       | `all`   | `all` \| `active` \| `partial` \| `debtor` |
| `offset`,`limit` | no    | `0` / `50` | Max `limit` = 500 |

### Status semantics

| Value     | Rule (per month) |
|-----------|------------------|
| `active`  | `remaining_debt <= 0` — paid in full, or month has no charge |
| `partial` | `0 < paid < total_debt` and `remaining_debt > 0` |
| `debtor`  | `paid == 0` and `total_debt > 0` |

### Response

```jsonc
{
  "system": "gennis", "scope_id": 4, "month": 5, "year": 2026,
  "students": [
    {
      "id": 123,
      "name": "Holmatov Bekzod",
      "phone": "+998…",            // Turon only (Gennis returns null)
      "class_label": "Math, English",  // Gennis: comma-joined group names; Turon: ClassNumber.number
      "monthly":        850000,
      "payment":        850000,
      "remaining_debt":      0,
      "discount":       150000,
      "discount_pct": 15,          // discount / (monthly + discount) × 100
      "status": "active"
    }
  ],
  "totals": {
    "count": 87, "monthly": 73…, "payment": 65…, "remaining_debt": 8…,
    "discount": 9…, "active": 70, "partial": 12, "debtor": 5
  },
  "pagination": { "total": 87, "offset": 0, "limit": 50, "has_more": true }
}
```

### Notes

- A student appearing in multiple groups (Gennis) is aggregated into one row
  (sums of `total_debt`, `payment`, `remaining_debt`, `total_discount`).
- `discount_pct` is rounded to the nearest integer.
- `totals` is computed across the **filtered** result set, not just the
  current page.

---

## Payments

`GET /api/v1/accountant/payments`

Per-channel KPI cards, 6-month revenue vs expense trend, paginated payment
list.

### Query

| Param         | Required | Default | Description |
|---------------|----------|---------|-------------|
| `system`      | yes      | —       | |
| `location_id` | gennis   | —       | |
| `branch_id`   | turon    | —       | |
| `month`,`year`| no       | today   | |
| `search`      | no       | —       | Filter list by student name/surname |
| `channel`     | no       | —       | Filter list by raw payment type name (`cash` / `click` / `bank` / `payme` / …) |
| `type`        | no       | —       | Filter list to `payment` or `discount` |
| `from`,`to`   | no       | —       | Filter list by `YYYY-MM-DD` range |
| `offset`,`limit` | no    | `0` / `50` | Max `limit` = 500 |

### Response

```jsonc
{
  "system":"gennis","scope_id":4,
  "month":5,"year":2026,
  "month_total": 142800000,

  "totals_by_channel": [
    { "channel":"cash",  "label":"Naqd",  "value": 45000000, "percent": 31.5 },
    { "channel":"click", "label":"Click", "value": 60000000, "percent": 42.0 },
    { "channel":"bank",  "label":"Bank",  "value": 37800000, "percent": 26.5 }
  ],

  "trend": [                                       // last 6 months
    { "month":12,"year":2025,"label":"Dek","revenue":110000000,"expense":46000000 }
  ],

  "items": [
    { "id":12345, "code":"#INV-12345",
      "student_name":"Holmatov Bekzod",
      "amount": 850000,
      "channel":"click", "channel_label":"Click",
      "date":"2026-01-19", "date_label":"19-yan",
      "type":"Oy to'lovi",     // "Oy to'lovi" | "Chegirma"
      "status":"To'landi"      // "To'landi"   | "Chegirma"
    }
  ],
  "pagination": { "total": 124, "offset": 0, "limit": 50, "has_more": true }
}
```

### Notes

- `expense` in `trend` = salaries paid that month + overhead-log payments that month. Different mix from `/dashboard` where it's only today.
- `code` is `"#INV-{id}"` — purely a display label, not stored in any DB.
- `type=discount` lists rows where `payment=False` (Gennis) or `status=False` (Turon).

---

## Overheads

`GET /api/v1/accountant/overheads`

Line-item expense list + 6-month revenue vs overhead-expense chart +
breakdown totals.

### Query

| Param              | Required | Default | Description |
|--------------------|----------|---------|-------------|
| `system`           | yes      | —       | |
| `location_id`      | gennis   | —       | |
| `branch_id`        | turon    | —       | |
| `month`,`year`     | no       | today   | |
| `search`           | no       | —       | Matches `name` or `category` |
| `overhead_type_id` | no       | —       | Filter by category (OverheadType id) |
| `payment_type_id`  | no       | —       | Filter by To'lov usuli |
| `offset`,`limit`   | no       | `0`/`50`| Max `limit` = 500 |

### Response

```jsonc
{
  "system":"gennis","scope_id":4,"month":5,"year":2026,

  "chart":[                                        // 6 points, oldest first
    {"month":12,"year":2025,"label":"Dek","revenue":81000000,"expense":38000000}
  ],

  "overheads":[
    { "id":123, "name":"Yanvar ijarasi", "category":"Ijara", "category_id":4,
      "amount":15000000,
      "branch_name":"Chilonzor", "branch_id":4,
      "date":"2026-01-01",
      "payment_type":"Bank o'tkazma", "payment_type_id":2 }
  ],

  "totals":{
    "count": 5,
    "amount": 29600000,
    "by_payment_type":[
      {"payment_type_id":1, "payment_type":"Naqd",  "amount": 6300000},
      {"payment_type_id":2, "payment_type":"Bank",  "amount":16500000}
    ],
    "by_category":[
      {"category_id":4, "category":"Ijara",     "amount":15000000},
      {"category_id":5, "category":"Kommunal",  "amount": 4200000}
    ]
  },
  "pagination":{ "total":5, "offset":0, "limit":50, "has_more":false }
}
```

### Notes

- Gennis list comes from the `overhead` table (legacy), joined to
  `overheadtype`, `paymenttypes`, `locations`, `calendarday`.
- Turon list comes from `overhead_overhead`; `date` is `overhead.created`.
- The chart adds in any `OverheadTypeLogPayment` rows whose `overhead_id` is
  still `NULL` — split payments that haven't yet been rolled into a legacy
  `Overhead` row. Once a log is fully paid, the corresponding `Overhead` row
  is created and `overhead_id` is set; those rows are then counted via the
  legacy total and **not** double-counted from the split table.

---

## Salaries

`GET /api/v1/accountant/salaries`

KPI cards (Jami hisoblangan / Bonuslar / Avans / Qolgan) + per-employee
table.

### Query

| Param         | Required | Default | Description |
|---------------|----------|---------|-------------|
| `system`      | yes      | —       | |
| `location_id` | gennis   | —       | |
| `branch_id`   | turon    | —       | |
| `month`,`year`| no       | today   | |
| `search`      | no       | —       | Name/surname |
| `role`        | no       | `all`   | `all` \| `teacher` \| `assistent` \| `staff` |
| `status`      | no       | `all`   | `all` \| `pending` \| `partial` \| `paid` |
| `offset`,`limit` | no    | `0`/`50`| Max `limit` = 500 |

### Status semantics

| Value      | Rule |
|------------|------|
| `paid`     | `advance >= total` |
| `partial`  | `0 < advance < total` |
| `pending`  | `advance == 0` |

`total = base_salary + bonus`.
`bonus` = `black_salary` in Gennis (off-the-books supplement); Turon has no
equivalent column, so `bonus` is always `0` and `bonus_employee_count` is
`0`.

### Response

```jsonc
{
  "system":"gennis","scope_id":4,"month":5,"year":2026,

  "kpis":{
    "accrued":    73000000,    // sum(total_salary)
    "bonus_total": 4500000,    // sum(black_salary)
    "bonus_employee_count": 3,
    "advance":   42000000,     // sum(taken_money)
    "remaining": 30000000      // sum(remaining_salary)
  },

  "rows":[
    { "id":11, "employee_id":7,
      "name":"Karimova Feruza", "role":"teacher",
      "position":"Matematika",        // subject (teachers) or profession (staff); null for assistents
      "hours":null, "rate_per_hour":null,   // not tracked
      "base_salary": 5000000,
      "bonus":        500000,
      "advance":     2500000,
      "total":       5500000,
      "remaining":   3000000,
      "status":"partial" }
  ],
  "pagination":{ "total":24, "offset":0, "limit":50, "has_more":false }
}
```

### Notes

- One row per `(employee, month)`. The salary tables that drive this:
  - Gennis: `teachersalary`, `asistent_salary`, `staffsalary`
  - Turon:  `teachers_teachersalary`, `user_usersalary`
- `hours` / `rate_per_hour` are placeholders — neither system stores them.
  Render `"-"` in those columns and skip "rate × hours = base" math.

---

## Debts

`GET /api/v1/accountant/debts`

Three tabs:

- `students` — students with unpaid balance for the month (O'quvchi qarzlari)
- `given`    — branch loans **issued** by the school, `direction=out` (Berilgan qarzlar)
- `taken`    — branch loans **received** by the school, `direction=in` (Olingan qarzlar)

### Query

| Param         | Required        | Default     | Description |
|---------------|-----------------|-------------|-------------|
| `system`      | yes             | —           | |
| `tab`         | yes             | `students`  | `students` \| `given` \| `taken` |
| `location_id` | gennis          | —           | |
| `branch_id`   | turon           | —           | |
| `month`,`year`| tab=students    | today       | Ignored for loan tabs |
| `status`      | loan tabs       | `all`       | `all` \| `active` \| `settled` \| `cancelled` |
| `search`      | no              | —           | Name / surname / phone / reason |
| `offset`,`limit` | no           | `0` / `50`  | Max `limit` = 500 |

### Response — tab `students`

```jsonc
{
  "system":"gennis","scope_id":4,"tab":"students","month":5,"year":2026,
  "rows":[
    { "student_id":42, "name":"Aliyev Ibrohim", "group_label":"10-A",
      "debt_amount":850000, "days_overdue":25,
      "discount_status":"cancelled", "discount_amount":-150000,
      "last_payment_date":null,
      "status":"overdue" }                 // overdue | pending
  ],
  "totals":{ "count":4, "debt_amount":3100000, "overdue_count":2, "pending_count":2 },
  "pagination":{ "total":4, "offset":0, "limit":50, "has_more":false }
}
```

Student row rules:

- Only students with `remaining_debt > 0` for the selected month are listed.
- `days_overdue` = `today − last-day-of-month` (`0` when the month hasn't
  ended yet).
- `status = "overdue"` if `days_overdue >= 14`, else `"pending"`.
- `discount_status`: `active` (`discount > 0`), `cancelled` (`discount < 0`),
  `none` (`0`).
- `last_payment_date` is the most recent paid payment across the student's
  whole history at that scope.

### Response — tabs `given` / `taken`

```jsonc
{
  "system":"gennis","scope_id":4,"tab":"given",
  "rows":[
    { "id":7, "management_id":42,
      "counterparty":"Hamidov Davron", "counterparty_phone":"+998…",
      "direction":"out", "principal_amount":15000000,
      "issued_date":"2026-04-01", "due_date":"2026-05-01", "settled_date":null,
      "days_overdue":17,
      "reason":"Yangi mebel",
      "status":"overdue" }   // active | overdue | settled | cancelled
  ],
  "totals":{
    "count":5,
    "principal_total":42000000,
    "active_total":15000000,
    "settled_total":20000000,
    "cancelled_total":7000000
  },
  "pagination":{ "total":5, "offset":0, "limit":50, "has_more":false }
}
```

Loan row rules:

- Source tables: `branch_loan` (Gennis), `branch_branchloan` (Turon).
- `status` is the stored value, **except** an `active` loan past its
  `due_date` is reported as `"overdue"` with the day count.
  When `status=active` filter is applied, those rows still show up because
  their stored status is still `active`.
- `counterparty` is `"<name> <surname>"`, falling back to the phone if both
  are empty.

---

## Frontend integration

### Axios client

```ts
import axios from 'axios';

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('accessToken');
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});
```

### React Query hooks (one per endpoint)

```ts
type Scope =
  | { system: 'gennis'; location_id: number }
  | { system: 'turon';  branch_id:  number };

const scopeParams = (s: Scope) =>
  s.system === 'gennis'
    ? { system: 'gennis', location_id: s.location_id }
    : { system: 'turon',  branch_id:  s.branch_id  };

export function useDashboard(scope: Scope) {
  return useQuery({
    queryKey: ['accountant', 'dashboard', scope],
    queryFn: () => api.get('/api/v1/accountant/dashboard',
      { params: scopeParams(scope) }).then(r => r.data),
    staleTime: 60_000,
  });
}

export function useStudents(scope: Scope, filters: {
  month?: number; year?: number; search?: string;
  status?: 'all' | 'active' | 'partial' | 'debtor';
  offset?: number; limit?: number;
}) {
  return useQuery({
    queryKey: ['accountant', 'students', scope, filters],
    queryFn: () => api.get('/api/v1/accountant/students',
      { params: { ...scopeParams(scope), ...filters } }).then(r => r.data),
    keepPreviousData: true,
  });
}

export function usePayments(scope: Scope, filters: {
  month?: number; year?: number;
  search?: string; channel?: string; type?: 'payment' | 'discount';
  from?: string; to?: string;
  offset?: number; limit?: number;
}) {
  return useQuery({
    queryKey: ['accountant', 'payments', scope, filters],
    queryFn: () => api.get('/api/v1/accountant/payments',
      { params: { ...scopeParams(scope), ...filters } }).then(r => r.data),
    keepPreviousData: true,
  });
}

export function useOverheads(scope: Scope, filters: {
  month?: number; year?: number;
  search?: string; overhead_type_id?: number; payment_type_id?: number;
  offset?: number; limit?: number;
}) {
  return useQuery({
    queryKey: ['accountant', 'overheads', scope, filters],
    queryFn: () => api.get('/api/v1/accountant/overheads',
      { params: { ...scopeParams(scope), ...filters } }).then(r => r.data),
    keepPreviousData: true,
  });
}

export function useSalaries(scope: Scope, filters: {
  month?: number; year?: number;
  search?: string;
  role?: 'all' | 'teacher' | 'assistent' | 'staff';
  status?: 'all' | 'pending' | 'partial' | 'paid';
  offset?: number; limit?: number;
}) {
  return useQuery({
    queryKey: ['accountant', 'salaries', scope, filters],
    queryFn: () => api.get('/api/v1/accountant/salaries',
      { params: { ...scopeParams(scope), ...filters } }).then(r => r.data),
    keepPreviousData: true,
  });
}

export function useDebts(scope: Scope, filters: {
  tab: 'students' | 'given' | 'taken';
  month?: number; year?: number;
  status?: 'all' | 'active' | 'settled' | 'cancelled';
  search?: string;
  offset?: number; limit?: number;
}) {
  return useQuery({
    queryKey: ['accountant', 'debts', scope, filters],
    queryFn: () => api.get('/api/v1/accountant/debts',
      { params: { ...scopeParams(scope), ...filters } }).then(r => r.data),
    keepPreviousData: true,
  });
}
```

### Status badge mapping (UI)

```tsx
const STUDENT_STATUS: Record<'active' | 'partial' | 'debtor', { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  active:  { label: 'Faol',     tone: 'success' },
  partial: { label: 'Qisman',   tone: 'warning' },
  debtor:  { label: 'Qarzdor',  tone: 'danger'  },
};

const DEBT_STATUS: Record<'overdue' | 'pending', { label: string; tone: 'danger' | 'warning' }> = {
  overdue: { label: 'Kechikkan',   tone: 'danger'  },
  pending: { label: 'Kutilmoqda',  tone: 'warning' },
};

const LOAN_STATUS: Record<'active' | 'overdue' | 'settled' | 'cancelled', { label: string; tone: string }> = {
  active:    { label: 'Aktiv',         tone: 'info'    },
  overdue:   { label: 'Kechikkan',     tone: 'danger'  },
  settled:   { label: 'To\'langan',     tone: 'success' },
  cancelled: { label: 'Bekor qilingan', tone: 'muted'   },
};

const SALARY_STATUS: Record<'pending' | 'partial' | 'paid', { label: string; tone: string }> = {
  pending: { label: 'Kutilmoqda', tone: 'warning' },
  partial: { label: 'Qisman',     tone: 'info'    },
  paid:    { label: 'To\'langan',  tone: 'success' },
};
```

### Channel label fallback

```ts
const CHANNEL = { cash: 'Naqd', click: 'Click', bank: 'Bank', payme: 'Payme' } as const;
const channelLabel = (raw?: string | null) =>
  raw ? (CHANNEL as any)[raw.toLowerCase()] ?? (raw[0].toUpperCase() + raw.slice(1)) : '—';
```

Prefer `channel_label` from the response when present; only fall back to
this mapping if the server returned `null`.

---

## Test scenarios

A focused list of acceptance checks. All requests below assume valid auth
and an existing scope. Adjust scope ids to your seed data.

### 1. Dashboard — Gennis

1. `GET /accountant/dashboard?system=gennis&location_id=4`
2. Verify:
   - `today_payments.value` equals `SUM(studentpayments.payment_sum)` where
     `payment=True`, `location_id=4`, and `calendarday.date=today`.
   - `today_expenses.salaries` equals the sum of teacher + assistent + staff
     salary payments for today at that location.
   - `today_expenses.overheads` equals `SUM(overheadtypelog_payment.amount)`
     where the parent log's `location_id=4` and `paid_date::date = today`.
   - `trend` has exactly 6 entries, ordered oldest → newest.

### 2. Dashboard — Turon

Same shape; replace `location_id` with `branch_id`; today's salaries come
from `teachers_teachersalarylist.date` and `user_usersalarylist.date`;
today's overheads come from `overhead_overhead.created=today` + split
payments.

### 3. Students filter & pagination

- `GET /accountant/students?system=gennis&location_id=4&status=debtor&limit=10` —
  every row's `status` must be `"debtor"`, and `totals.debtor === pagination.total`.
- `GET ?…&search=ali` — only rows where name/surname contains "ali" (case-insensitive).
- Page through with `offset=0,10,20` — `totals.count` is constant across pages;
  `pagination.has_more` flips to `false` on the last page.

### 4. Payments — channel KPI + trend reconciliation

- `month_total === sum(totals_by_channel[*].value)`.
- `sum(totals_by_channel[*].percent)` ≈ `100` (modulo rounding).
- `trend[5].revenue` for the current month must equal
  `/dashboard.monthly_income.value` for the same scope (same definition).

### 5. Payments — filters

- `channel=click` — every item has `channel === "click"`.
- `type=discount` — every item has `type === "Chegirma"` and `status === "Chegirma"`.
- `from=2026-01-01&to=2026-01-31` — all `item.date` values are in range.

### 6. Overheads chart vs list

For the same `month/year`:
- `sum(overheads[*].amount)` ≤ `chart[5].expense` (chart adds split-payment
  rows not yet materialized into a legacy `Overhead`).
- `totals.by_category` and `totals.by_payment_type` sums each equal
  `totals.amount`.

### 7. Salaries — status math

For each row: `total === base_salary + bonus`. `remaining` should equal
`max(0, total − advance)` (modulo black-salary nuances on Gennis where
fine/debt also play in — confirm with the `gennis/detail.py` salaries
endpoint which has the canonical computation).

KPI:
- `kpis.accrued === sum(rows[*].base_salary + rows[*].bonus)`
  (after `status=all` and unbounded `limit`).
- `kpis.advance === sum(rows[*].advance)`.
- `kpis.remaining === sum(rows[*].remaining)`.

### 8. Debts — students tab

- All rows have `debt_amount > 0`.
- `totals.overdue_count + totals.pending_count === totals.count`.
- For a row where today is still inside the month, `days_overdue === 0` and
  `status === "pending"`.

### 9. Debts — given vs taken

- `tab=given` returns only rows with `direction === "out"`.
- `tab=taken` returns only rows with `direction === "in"`.
- A loan whose `due_date < today` and stored `status="active"` comes back
  with `status="overdue"` and `days_overdue > 0`.
- `status=settled` filter excludes overdue/active rows.

### 10. Scope validation

- `GET /accountant/dashboard?system=gennis` (no `location_id`) → `400`.
- `GET /accountant/students?system=turon&location_id=1` (wrong scope) → `400`.

---

## Errors

| Code | When |
|------|------|
| `400` | Missing or wrong scope id for the chosen `system` |
| `404` | Calendar month/year not found in Gennis calendar tables (students/debts with explicit `month`/`year` for unseeded periods) |
| `422` | Bad query types (e.g. `month=13`, `year=1999`, `limit > 500`) |

All responses use FastAPI's default error envelope: `{ "detail": "…" }`.
