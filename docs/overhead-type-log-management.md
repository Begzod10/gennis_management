# OverheadTypeLog — frontend integration guide

Companion to [`overhead-split-payments.md`](./overhead-split-payments.md).
That doc covers the split-payment routes (add / list / delete / convert).
This one covers the **log itself**: how to list, generate, update, and
delete `OverheadTypeLog` rows.

| Project | Stack | Base URL |
|---|---|---|
| Gennis | Flask | `/account` |
| Turon | Django REST | `/api/Overhead` |
| Management (proxy) | FastAPI | `/api/v1` |

Migrations must be applied on Gennis and Turon servers before any of the new
routes work (see split-payments doc for the migration commands).

---

## What an `OverheadTypeLog` is

One row represents the obligation to pay a fixed overhead (rent, electricity,
gas, etc.) for a specific month at a specific location/branch.

```
OverheadTypeLog
  ├─ id
  ├─ overhead_type_id   → OverheadType ("Arenda", "Svet", ...)
  ├─ cost               billed amount for this month
  ├─ location_id (Gennis) / branch_id (Turon)
  ├─ calendar_month + calendar_year (Gennis) / date (Turon)
  ├─ is_paid            derived from payments (don't write directly)
  ├─ paid_date          derived from payments
  ├─ is_prepaid         true if paid in a previous month for this month
  ├─ overhead_id        legacy single-pay link; null when using splits
  ├─ deleted            soft-delete flag
  └─ payments[]         see split-payments doc
```

The system auto-generates one log per fixed `OverheadType` per month on the
first call to the monthly listing endpoint. Admin can also trigger generation
manually.

---

## 1. Routes

### 1.1 List logs for a month (existing — payment fields now included)

| | Gennis | Turon | Management proxy |
|---|---|---|---|
| **Method** | `GET` | `GET` | `GET` |
| **URL** | `/account/overhead_type_logs/<month>/<year>` | `/api/Overhead/overhead_type_logs/<month>/<year>/` | `/api/v1/overhead-type-logs/<month>/<year>` |
| **Query** | `location_id`, `status` | `branch_id`, `status` | `branch_id`, `location_id`, `status`, `source` |

`status` filter: `"paid"`, `"unpaid"`, `"all"` (default).

**Response (200):**

```json
{
  "success": true,
  "summary": {
    "total_count": 7,
    "paid_count": 3,
    "unpaid_count": 4,
    "total_sum": 18500000,
    "paid_sum": 8000000,
    "unpaid_sum": 10500000
  },
  "data": [
    {
      "id": 12,
      "overhead_type_id": 22,
      "overhead_type_name": "Arenda",
      "cost": 4000000,
      "is_paid": false,
      "is_prepaid": false,
      "paid_date": null,
      "overhead_id": null,
      "location_id": 3,
      "calendar_month": 65,
      "calendar_year": 4,
      "paid_amount": 1000000,
      "remaining_amount": 3000000,
      "payment_status": "partial",
      "payments": [ /* see split-payments doc */ ]
    }
  ]
}
```

**Key fields for the UI:**

- `payment_status` drives the badge / progress bar
- `paid_amount` / `remaining_amount` drive the progress display
- `payments[]` is the per-installment breakdown
- `summary.paid_sum` now adds up `paid_amount` (partial contributions count
  proportionally), not just `cost` of fully-paid logs

### 1.2 Generate logs for a month (existing)

Creates `OverheadTypeLog` rows for every `OverheadType` (with `changeable=False`
and a non-null `cost`) that doesn't already have one for the given month.

| | Gennis | Turon |
|---|---|---|
| **Method** | `POST` | `POST` |
| **URL** | `/account/overhead_type_logs/generate/<month>/<year>` | `/api/Overhead/overhead_type_logs/generate/<month>/<year>/` |
| **Body** | `{ "location_id": 3 }` | `{ "branch_id": 6 }` |

**Success (200):**

```json
{ "success": true, "message": "Loglar yaratildi" }
```

> Note: `OverheadType` rows themselves are managed elsewhere (CRUD on the
> _types_, not the logs). This endpoint only ensures the month's log entries
> exist for fixed (non-changeable) types.

### 1.3 Update an OverheadTypeLog (new)

Only `cost` is editable. Everything else is either FK-stable or system-managed.

| | Gennis | Turon |
|---|---|---|
| **Method** | `PATCH` | `PATCH` |
| **URL** | `/account/overhead_type_logs/<log_id>` | `/api/Overhead/overhead_type_logs/<log_id>/update/` |

**Body:**

```json
{ "cost": 5000000 }
```

**Success (200):**

```json
{
  "success": true,
  "message": "Log yangilandi",
  "log": { /* updated log with new cost and recomputed status */ }
}
```

Side effects:
- If the log uses **split payments**, `is_paid` / `paid_date` /
  `payment_status` are recomputed against the new cost. Raising cost can flip
  `paid` → `partial`; lowering cost can flip `partial` → `paid`.
- If the log is **legacy single-pay** (`overhead_id` set, no splits),
  `is_paid` / `paid_date` are left untouched.

**Errors:**

| HTTP | `message` |
|---|---|
| 400 | `Yangilanadigan maydonlar yo'q` (empty body) |
| 400 | `Ruxsat etilgan maydon yo'q (faqat: cost)` (no recognised fields) |
| 400 | `cost butun son bo'lishi kerak` |
| 400 | `cost musbat bo'lishi kerak` |
| 400 | `Yangi cost to'langan summadan kichik bo'lishi mumkin emas (X so'm). Avval to'lovlarni o'chiring.` — body has `paid_amount` |
| 400 | `Log o'chirilgan` |
| 404 | `Log topilmadi` |

### 1.4 Delete an OverheadTypeLog (new)

Soft-deletes the log (sets `deleted=true`). The log disappears from the
monthly listing afterward.

| | Gennis | Turon |
|---|---|---|
| **Method** | `DELETE` | `DELETE` |
| **URL** | `/account/overhead_type_logs/<log_id>` | `/api/Overhead/overhead_type_logs/<log_id>/delete/` |

**Success (200):**

```json
{
  "success": true,
  "message": "Log o'chirildi",
  "log": { /* the log, now with deleted=true */ }
}
```

**Refusal cases** (the route never silently destroys financial data):

| HTTP | When | `message` |
|---|---|---|
| 400 | Log already deleted | `Log allaqachon o'chirilgan` |
| 400 | Log has any active split payments | `Logda faol to'lovlar bor. Avval ularni o'chiring.` |
| 400 | Log was paid via the legacy single-pay flow (`overhead_id` set) | `Log legacy bir martalik to'lov bilan to'langan. Avval /convert-to-split qiling, so'ng to'lovni o'chiring.` |
| 404 | Log not found | `Log topilmadi` |

**To delete a log that has financial records, the admin's flow is:**

1. If `payment_status === "paid"` AND `payments.length === 0` (legacy):
   call `POST /convert-to-split` first.
2. Call `DELETE /payments/<id>` for every active payment row.
3. Now `payment_status === "unpaid"` and `overhead_id === null` → DELETE log.

---

## 2. Pay routes (cross-reference)

Detailed in [`overhead-split-payments.md`](./overhead-split-payments.md). Short
summary so this doc is self-contained:

| Route | Purpose |
|---|---|
| `POST /payments` (Gennis) / `POST /payments/add/` (Turon) | Add a partial / split payment installment |
| `GET /payments` / `GET /payments/` | List active payments for one log |
| `DELETE /payments/<id>` / `DELETE /payments/<id>/delete/` | Soft-delete a payment + hard-delete its accounting Overhead |
| `POST /convert-to-split` / `POST /convert-to-split/` | Migrate a legacy single-pay log into the split-payment model |
| `POST /pay` / `POST /pay/` (legacy) | Old single-shot full payment. Refuses if splits exist. New UIs should prefer `POST /payments`. |

### Drill-in from the expense lists

Each row returned by the expense-history lists carries optional
`payment_id` + `overhead_type_log_id` fields when the underlying `Overhead`
came from a split payment. The frontend can jump straight from
"cash event in the expense list" into "the bill that drove it":

| Expense list route | Source |
|---|---|
| `GET /account/account_info/overhead/?locationId=...` | Gennis |
| `GET /api/Overhead/overheads/?branch=...` | Turon |

Detailed shape and a React snippet are in
[`overhead-split-payments.md` §2.3](./overhead-split-payments.md#23-expense-list--new-link-fields-per-row).

---

## 3. React integration sketch

```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const GENNIS_BASE = '/account';
const TURON_BASE = '/api/Overhead';

type LogRow = {
  id: number;
  overhead_type_id: number;
  overhead_type_name: string;
  cost: number;
  is_paid: boolean;
  is_prepaid: boolean;
  paid_date: string | null;
  overhead_id: number | null;
  location_id?: number;
  branch_id?: number;
  paid_amount: number;
  remaining_amount: number;
  payment_status: 'unpaid' | 'partial' | 'paid';
  payments: Array<{
    id: number;
    payment_type_id: number;
    payment_type_name: string | null;
    amount: number;
    paid_date: string;
    note: string | null;
  }>;
};

type MonthlyListResponse = {
  success: true;
  summary: {
    total_count: number; paid_count: number; unpaid_count: number;
    total_sum: number; paid_sum: number; unpaid_sum: number;
  };
  data: LogRow[];
};

// 3.1 List + filter
export function useOverheadTypeLogs(args: {
  source: 'gennis' | 'turon' | 'management';
  month: number; year: number;
  branchId?: number; locationId?: number;
  status?: 'all' | 'paid' | 'unpaid';
}) {
  const { source, month, year, branchId, locationId, status = 'all' } = args;
  const params: Record<string, string | number> = { status };
  if (branchId != null) params.branch_id = branchId;
  if (locationId != null) params.location_id = locationId;

  const base =
    source === 'gennis' ? GENNIS_BASE :
    source === 'turon'  ? TURON_BASE :
    '/api/v1';
  const slash = source === 'turon' ? '/' : '';

  return useQuery({
    queryKey: ['overhead-type-logs', source, month, year, params],
    queryFn: async (): Promise<MonthlyListResponse> => {
      const { data } = await axios.get(
        `${base}/overhead_type_logs/${month}/${year}${slash}`,
        { params },
      );
      return data;
    },
  });
}

// 3.2 Generate
export function useGenerateLogs(source: 'gennis' | 'turon', month: number, year: number) {
  const qc = useQueryClient();
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;
  const slash = source === 'turon' ? '/' : '';
  return useMutation({
    mutationFn: async (scope: { branch_id?: number; location_id?: number }) => {
      const { data } = await axios.post(
        `${base}/overhead_type_logs/generate/${month}/${year}${slash}`, scope,
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['overhead-type-logs'] }),
  });
}

// 3.3 Update (cost)
export function useUpdateOverheadTypeLog(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const path = source === 'gennis'
    ? `${GENNIS_BASE}/overhead_type_logs/${logId}`
    : `${TURON_BASE}/overhead_type_logs/${logId}/update/`;
  return useMutation({
    mutationFn: async (body: { cost?: number }) => {
      const { data } = await axios.patch(path, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['overhead-type-logs'] }),
  });
}

// 3.4 Delete
export function useDeleteOverheadTypeLog(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const path = source === 'gennis'
    ? `${GENNIS_BASE}/overhead_type_logs/${logId}`
    : `${TURON_BASE}/overhead_type_logs/${logId}/delete/`;
  return useMutation({
    mutationFn: async () => {
      const { data } = await axios.delete(path);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['overhead-type-logs'] }),
  });
}
```

### UI rules

For each log row in the monthly table:

| Condition | UI action |
|---|---|
| `payment_status === "unpaid"` AND `!overhead_id` | Show **Edit cost** + **Delete log** + **Pay** |
| `payment_status === "partial"` | Show **Edit cost** + **Add payment** + **View payments**. Hide Delete (refused server-side). |
| `payment_status === "paid"` AND `payments.length > 0` | Show **View payments**. Edit cost still allowed (may flip back to partial — surface warning). Delete hidden. |
| `payment_status === "paid"` AND `payments.length === 0` (legacy) | Show **Convert to split** action. Edit cost not allowed (it's a legacy fixed record). Delete hidden. |

For the **edit-cost modal**:
- Validate `cost > 0` client-side
- On 400 with `paid_amount` in body, show "Already paid X som — cannot drop
  below that. Delete some payments first."
- If `payment_status === "paid"` and admin raises cost, warn that the log will
  reopen as `partial`

For the **delete confirmation modal**:
- Only available when `payment_status === "unpaid"` AND `!overhead_id`
- Confirmation text: "Bu logni o'chirmoqchimisiz? Bu amalni bekor qilib bo'lmaydi."

---

## 4. Test scenarios

All tests use Gennis paths; Turon equivalents are identical other than the URL
shape.

### 4.1 Generate then list

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /generate/5/2026 {location_id: 3}` | 200, success |
| 2 | `GET /5/2026?location_id=3` | data[] contains one row per fixed OverheadType, all `payment_status="unpaid"` |
| 3 | `GET /5/2026?location_id=3&status=paid` | `data[].length === 0` |

### 4.2 Update cost (basic + flip recompute)

| Step | Request | Expected |
|---|---|---|
| 1 | `PATCH /<L> {cost: 4000000}` | 200, `cost=4M`, `payment_status=unpaid` |
| 2 | `POST /<L>/payments {amount: 4000000, ...}` | 200, `payment_status=paid` |
| 3 | `PATCH /<L> {cost: 6000000}` | 200, `cost=6M`, `is_paid=false`, `payment_status=partial`, `remaining=2M` |
| 4 | `PATCH /<L> {cost: 4000000}` | **400** "Yangi cost to'langan summadan kichik bo'lishi mumkin emas (4,000,000 so'm)..." (body has `paid_amount=4000000`) — wait, this is allowed since new=4M >= paid=4M. Let's use 3M: `PATCH /<L> {cost: 3000000}` | **400** body has `paid_amount=4000000` |
| 5 | `PATCH /<L> {cost: 5000000}` | 200, recomputed back to `paid` (paid=4M, cost=5M means `remaining=1M`, `partial`) — actually re-evaluate carefully |
| 6 | `PATCH /<L> {}` | 400 "Yangilanadigan maydonlar yo'q" |
| 7 | `PATCH /<L> {is_paid: true}` | 400 "Ruxsat etilgan maydon yo'q (faqat: cost)" |

> Notes on step 5: with `paid=4M, cost=5M` the log becomes `partial` again
> (remaining=1M). It only stays `paid` if `paid >= cost`. Re-check the
> behaviour in your UI tests.

### 4.3 Delete log — happy path

| Step | Request | Expected |
|---|---|---|
| 1 | Generate logs, pick log `L` with `payment_status=unpaid` and `overhead_id=null` | — |
| 2 | `DELETE /<L>` | 200, `log.deleted === true` |
| 3 | `GET /5/2026` | `L` is no longer in `data[]` |
| 4 | `DELETE /<L>` again | **400** "Log allaqachon o'chirilgan" |
| 5 | `DELETE /<99999>` (non-existent) | **404** "Log topilmadi" |

### 4.4 Delete log refuses when payments exist

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /<L>/payments {amount: 1000000, ...}` | 200, partial |
| 2 | `DELETE /<L>` | **400** "Logda faol to'lovlar bor. Avval ularni o'chiring." |
| 3 | `DELETE /payments/<payment_id>` | 200, payment soft-deleted |
| 4 | `DELETE /<L>` | 200, log soft-deleted |

### 4.5 Delete log refuses when legacy-paid

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /pay {log_id: L, ...}` (legacy single-pay) | 200, `is_paid=true`, `overhead_id` set |
| 2 | `DELETE /<L>` | **400** "Log legacy bir martalik to'lov bilan to'langan..." |
| 3 | `POST /<L>/convert-to-split` | 200, payment created, `overhead_id=null` on the log |
| 4 | `DELETE /<L>` | **400** "Logda faol to'lovlar bor..." (the converted payment) |
| 5 | `DELETE /payments/<payment_id>` | 200 |
| 6 | `DELETE /<L>` | 200, log soft-deleted |

### 4.6 Concurrent update + payment

(Manual / pen-and-paper — formal load test optional.)

`L` has `cost=4M`, `paid=1M`. In two terminals near-simultaneously:

```bash
# A
curl -X PATCH ".../<L>" -d '{"cost": 5000000}'
# B
curl -X POST ".../<L>/payments" -d '{"amount": 3000000, ...}'
```

Expected: both succeed. Whoever gets the lock first commits, the other waits
then commits using fresh state. Final log: `cost=5M`, `paid=4M`,
`payment_status=partial`, `remaining=1M`. No corruption — the `with_for_update`
serialises the two writes.

---

## 5. Things to remember

- **No new migrations for the update/delete routes** — they reuse existing
  columns (`cost`, `deleted`). The migration you still need on each backend
  is the `OverheadTypeLogPayment` table from the split-payments work.
- **Soft delete only** — `OverheadTypeLog.deleted=True` doesn't free the row
  for re-use; if you `POST /generate/...` for the same month again, the
  duplicate-detection looks at `deleted=False` rows only, so a deleted log
  will not be regenerated automatically. You'd need a separate undelete
  route (not provided) to bring it back.
- **Locking** — all log-mutating routes (`add payment`, `delete payment`,
  `convert-to-split`, `PATCH`, `DELETE`) acquire `SELECT FOR UPDATE` on the
  log row, so concurrent mutations on the same log serialise cleanly.
