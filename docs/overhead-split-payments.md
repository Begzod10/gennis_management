# Overhead-type-log: split payments — frontend integration guide

Adds support for paying a single overhead-type log (rent, electricity, etc.) in
**multiple installments** with different payment methods. Replaces the old
binary "fully paid or not" model with `unpaid` / `partial` / `paid` states.

Applies to three backends:

| Project | Stack | Base URL |
|---|---|---|
| Gennis | Flask | `/account/...` |
| Turon | Django REST | `/api/Overhead/...` |
| Management (proxy) | FastAPI | `/api/v1/...` |

Migrations must be applied on Gennis and Turon servers before any of the new
routes will work:

```bash
# Gennis
flask db migrate -m "add overheadtypelog_payment"
flask db upgrade

# Turon
python manage.py makemigrations overhead
python manage.py migrate overhead
```

Management has no migration of its own — it reads via SQLAlchemy mirrors.

---

## Data model

```
OverheadTypeLog (one per fixed expense per month, e.g. "Arenda - 2026-05")
  ├─ cost: 4_000_000
  ├─ is_paid: true | false        ← auto-derived from sum of active payments
  ├─ paid_date: latest payment's date, or null
  ├─ overhead_id: legacy single-payment Overhead row, or null
  └─ payments[] (new): OverheadTypeLogPayment
        ├─ payment_type_id (cash / click / payme / transfer / ...)
        ├─ overhead_id (each payment writes its own Overhead row for accounting)
        ├─ amount
        ├─ paid_date
        ├─ note
        └─ deleted (soft-delete)

Derived fields surfaced on the log:
  paid_amount     = SUM(payments where !deleted)
  remaining_amount = max(0, cost - paid_amount)
  payment_status  = "unpaid" | "partial" | "paid"
```

---

## 1. New routes

### 1.1 Add a partial / split payment

| | Gennis | Turon |
|---|---|---|
| **Method** | `POST` | `POST` |
| **URL** | `/account/overhead_type_logs/<log_id>/payments` | `/api/Overhead/overhead_type_logs/<log_id>/payments/add/` |
| **Auth** | JWT (Authorization: Bearer …) | JWT |

**Body (JSON):**

```json
{
  "payment_type_id": 1,
  "amount": 1000000,
  "date": "2026-05-14",
  "location_id": 3,           // Gennis only
  "branch_id": 6,             // Turon only
  "note": "Cash from kassa"   // optional
}
```

**Success (200):**

```json
{
  "success": true,
  "message": "1000000 so'm to'lov qo'shildi",
  "payment": {
    "id": 12,
    "overhead_type_log_id": 7,
    "payment_type_id": 1,
    "payment_type_name": "Cash",
    "overhead_id": 5570,
    "amount": 1000000,
    "paid_date": "14.05.2026",
    "note": "Cash from kassa"
  },
  "log": {
    "id": 7,
    "cost": 4000000,
    "is_paid": false,
    "paid_amount": 1000000,
    "remaining_amount": 3000000,
    "payment_status": "partial",
    "payments": [ /* … */ ]
  }
}
```

**Error responses:**

| HTTP | Reason | `message` |
|---|---|---|
| 400 | Body missing required field | `payment_type_id, amount, date, location_id majburiy` |
| 400 | `amount` not integer | `amount butun son bo'lishi kerak` |
| 400 | `amount <= 0` | `amount musbat bo'lishi kerak` |
| 400 | Bad `date` format | `date format: YYYY-MM-DD` |
| 400 | Log soft-deleted | `Log o'chirilgan` |
| 400 | Log has no `cost` set | `Log narxi belgilanmagan` |
| 400 | Overpayment | `To'lov summasi qoldiqdan oshib ketmasligi kerak. Qoldiq: 3,000,000 so'm` — also returns `"remaining_amount": 3000000` in the body so the UI can prefill |
| 400 | Log was paid via legacy single-pay flow | `Bu log avval bir martalik to'lov bilan to'langan. Avval u to'lovni bekor qiling.` |
| 404 | Log not found | `Log topilmadi` |

### 1.2 List payments for one log

| | Gennis | Turon |
|---|---|---|
| **Method** | `GET` | `GET` |
| **URL** | `/account/overhead_type_logs/<log_id>/payments` | `/api/Overhead/overhead_type_logs/<log_id>/payments/` |

**Response (200):**

```json
{
  "success": true,
  "log_id": 7,
  "cost": 4000000,
  "paid_amount": 1000000,
  "remaining_amount": 3000000,
  "payment_status": "partial",
  "payments": [
    {
      "id": 12,
      "payment_type_id": 1,
      "payment_type_name": "Cash",
      "overhead_id": 5570,
      "amount": 1000000,
      "paid_date": "14.05.2026",
      "note": null
    }
  ]
}
```

### 1.3 Delete a payment

| | Gennis | Turon |
|---|---|---|
| **Method** | `DELETE` | `DELETE` |
| **URL** | `/account/overhead_type_logs/payments/<payment_id>` | `/api/Overhead/overhead_type_logs/payments/<payment_id>/delete/` |

Soft-deletes the payment row and hard-deletes its accounting `Overhead` row,
then recomputes `is_paid` / `paid_date` / `payment_status`.

**Success (200):**

```json
{
  "success": true,
  "message": "To'lov o'chirildi",
  "log": { /* updated log with new totals */ }
}
```

**Errors:**

| HTTP | `message` |
|---|---|
| 400 | `Allaqachon o'chirilgan` |
| 404 | `Payment topilmadi` |

### 1.4 Update an OverheadTypeLog (editable fields)

Currently only `cost` is editable. The rest (`is_paid`, `paid_date`,
`overhead_id`, calendar / type / location FKs) are managed by the system.

| | Gennis | Turon |
|---|---|---|
| **Method** | `PATCH` | `PATCH` |
| **URL** | `/account/overhead_type_logs/<log_id>` | `/api/Overhead/overhead_type_logs/<log_id>/update/` |

**Body (JSON):**

```json
{ "cost": 5000000 }
```

**Success (200):**

```json
{
  "success": true,
  "message": "Log yangilandi",
  "log": { /* updated log with new cost + recomputed status */ }
}
```

If the log has split payments, `is_paid` / `paid_date` / `payment_status` are
recomputed against the new cost (e.g., raising cost from 3M to 5M may flip an
already-paid log back to `partial`).

**Errors:**

| HTTP | `message` |
|---|---|
| 400 | `Yangilanadigan maydonlar yo'q` (empty body) |
| 400 | `Ruxsat etilgan maydon yo'q (faqat: cost)` (no recognised fields) |
| 400 | `cost butun son bo'lishi kerak` |
| 400 | `cost musbat bo'lishi kerak` |
| 400 | `Yangi cost to'langan summadan kichik bo'lishi mumkin emas (X so'm). Avval to'lovlarni o'chiring.` — body also includes `paid_amount` |
| 400 | `Log o'chirilgan` |
| 404 | `Log topilmadi` |

### 1.5 Convert a legacy single-pay log to split-payment

Some logs were paid via the old `/overhead_type_logs/pay` endpoint, which sets
`log.overhead_id` to a single Overhead row. The new endpoints refuse to add
splits to those logs. Use this route to migrate one into the split-payment
model without losing the accounting record.

| | Gennis | Turon |
|---|---|---|
| **Method** | `POST` | `POST` |
| **URL** | `/account/overhead_type_logs/<log_id>/convert-to-split` | `/api/Overhead/overhead_type_logs/<log_id>/convert-to-split/` |
| **Body** | (empty) | (empty) |

Internally it creates one `OverheadTypeLogPayment` row reusing the legacy
Overhead's amount / payment_type / date (note: `"Converted from legacy single
payment"`), then clears `log.overhead_id`. The legacy `Overhead` row itself is
kept intact and reattached via `payment.overhead_id`.

**Success (200):**

```json
{
  "success": true,
  "message": "Log split-payment formatiga o'tkazildi",
  "payment": { /* the new payment row */ },
  "log": { /* log now with is_paid=true, payment_status="paid", payments[1] */ }
}
```

**Errors:**

| HTTP | `message` |
|---|---|
| 400 | `Log o'chirilgan` |
| 400 | `Bu logda allaqachon split to'lovlar mavjud.` |
| 400 | `Bu log legacy bir martalik to'lov bilan to'lanmagan, konversiya kerak emas.` |
| 400 | `Legacy Overhead yo'q. log.overhead_id ni qo'lda tozalang.` |
| 404 | `Log topilmadi` |

---

## 2. Routes whose behavior changed

### 2.1 Legacy "pay" endpoint

| | Gennis | Turon |
|---|---|---|
| **URL** | `POST /account/overhead_type_logs/pay` | `POST /api/Overhead/overhead_type_logs/pay/` |

Still works exactly as before (full single payment, sets `is_paid=true`,
creates one `Overhead` row, supports prepayments via `paid_for_month`), with
**two new refusal cases**:

- If the target log has any active split payments → 400
  `Bu logga qisman to'lovlar mavjud. Yangi to'lov uchun /overhead_type_logs/<id>/payments dan foydalaning.`
- Prepay branch: same check on the target month's log

In the frontend, this means: if the user is looking at a log with
`payment_status === "partial"`, hide / disable the "Pay full" button — they
should use the partial-payment flow instead.

### 2.2 Monthly listing (management proxy)

`GET /api/v1/overhead-type-logs/{month}/{year}?branch_id=&location_id=&status=`

Each row in `data[]` now also includes:

```json
{
  "paid_amount": 1000000,
  "remaining_amount": 3000000,
  "payment_status": "unpaid" | "partial" | "paid",
  "payments": [ /* same shape as 1.2 above */ ]
}
```

And the top-level `summary.paid_sum` now adds up `paid_amount` (partial
payments contribute proportionally) instead of jumping by full `cost` only
when `is_paid=true`. Old fields stay where they were.

### 2.3 Gennis home_screen overhead bucketing

`GET /account/account_overhead_total/?month=&year=&location_id=` returns
`total_gaz` / `total_svet` / `total_suv` / `total_arenda` / `total_other`.

Previously these buckets were filled by a case-sensitive comparison on the
free-text `Overhead.item_name` (`"gaz"`, `"svet"`, …) — so any `Overhead` row
with capitalized `item_name = "Svet"` (the pattern the legacy pay endpoint and
the new split-payment endpoint both use) fell into `total_other`.

Now the bucket is decided by `overhead_type.name` when present, falling back
to lowercase `item_name` for pre-OverheadType legacy rows. Split payments
land in the right bucket without any frontend change.

---

## 3. React integration sketch

### 3.1 Hook to fetch + manipulate one log's payments

```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

type PaymentStatus = 'unpaid' | 'partial' | 'paid';

type Payment = {
  id: number;
  payment_type_id: number;
  payment_type_name: string | null;
  overhead_id: number | null;
  amount: number;
  paid_date: string; // "DD.MM.YYYY"
  note: string | null;
};

type LogWithPayments = {
  success: boolean;
  log_id: number;
  cost: number;
  paid_amount: number;
  remaining_amount: number;
  payment_status: PaymentStatus;
  payments: Payment[];
};

const GENNIS_BASE = '/account';
const TURON_BASE = '/api/Overhead';

export function useLogPayments(source: 'gennis' | 'turon', logId: number) {
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;
  const suffix = source === 'gennis' ? '' : '/';

  return useQuery({
    queryKey: ['overhead-log-payments', source, logId],
    queryFn: async (): Promise<LogWithPayments> => {
      const { data } = await axios.get(
        `${base}/overhead_type_logs/${logId}/payments${suffix}`,
      );
      return data;
    },
  });
}

type AddPaymentInput = {
  payment_type_id: number;
  amount: number;
  date: string;          // "YYYY-MM-DD"
  location_id?: number;  // Gennis
  branch_id?: number;    // Turon
  note?: string;
};

export function useAddPayment(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;
  const path = source === 'gennis'
    ? `${base}/overhead_type_logs/${logId}/payments`
    : `${base}/overhead_type_logs/${logId}/payments/add/`;

  return useMutation({
    mutationFn: async (input: AddPaymentInput) => {
      const { data } = await axios.post(path, input);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['overhead-log-payments', source, logId] });
      qc.invalidateQueries({ queryKey: ['overhead-type-logs'] }); // list view
    },
  });
}

export function useDeletePayment(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;

  return useMutation({
    mutationFn: async (paymentId: number) => {
      const path = source === 'gennis'
        ? `${base}/overhead_type_logs/payments/${paymentId}`
        : `${base}/overhead_type_logs/payments/${paymentId}/delete/`;
      const { data } = await axios.delete(path);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['overhead-log-payments', source, logId] });
      qc.invalidateQueries({ queryKey: ['overhead-type-logs'] });
    },
  });
}

export function useConvertToSplit(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;
  const suffix = source === 'gennis' ? '' : '/';

  return useMutation({
    mutationFn: async () => {
      const { data } = await axios.post(
        `${base}/overhead_type_logs/${logId}/convert-to-split${suffix}`,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['overhead-log-payments', source, logId] });
      qc.invalidateQueries({ queryKey: ['overhead-type-logs'] });
    },
  });
}

type UpdateLogInput = { cost?: number };

export function useUpdateLog(source: 'gennis' | 'turon', logId: number) {
  const qc = useQueryClient();
  const base = source === 'gennis' ? GENNIS_BASE : TURON_BASE;
  const path = source === 'gennis'
    ? `${base}/overhead_type_logs/${logId}`
    : `${base}/overhead_type_logs/${logId}/update/`;

  return useMutation({
    mutationFn: async (input: UpdateLogInput) => {
      const { data } = await axios.patch(path, input);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['overhead-log-payments', source, logId] });
      qc.invalidateQueries({ queryKey: ['overhead-type-logs'] });
    },
  });
}
```

### 3.2 UI rules

For each row in the monthly list:

| `payment_status` | Show |
|---|---|
| `unpaid` | "Pay" button → opens add-payment modal (also exposes "Pay full"  which can call legacy `/pay` for backwards-compat) |
| `partial` | Progress bar (`paid_amount / cost`), "Add payment" button, "View payments" link |
| `paid` | Green badge with `paid_date`, "View payments" link, **no add button** (already at remaining=0) |

For the **add-payment modal**:

- Prefill `amount` with `remaining_amount` and let the user reduce it.
- Validate client-side: `0 < amount <= remaining_amount`.
- Show payment-type radio buttons (Cash / Click / Payme / Transfer …).
- On 400 with `remaining_amount` in the body, show the server's message and
  reset the input to that number (covers race-condition rejections).

For the **legacy-paid log → convert-to-split flow**:

- If `payment_status === "paid"` AND `payments.length === 0` (= legacy), show
  a "Convert to split" action so the user can later edit / delete that
  single payment. Otherwise hide it.

---

## 4. Test scenarios

All tests assume an unpaid log `L` with `cost = 4_000_000` and at least two
payment types (e.g., Cash id=1, Click id=2).

### 4.1 Happy path: full payment in two installments

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /payments {amount: 1000000, payment_type_id: 1}` | `payment_status=partial`, `paid=1M`, `remaining=3M` |
| 2 | `POST /payments {amount: 3000000, payment_type_id: 2}` | `payment_status=paid`, `paid=4M`, `remaining=0`, `is_paid=true` |
| 3 | `GET /payments` | `payments[].length == 2`, statuses match |

### 4.2 Overpayment is rejected

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /payments {amount: 4500000}` | 400, `message` mentions remaining=4M, body has `remaining_amount: 4000000` |
| 2 | `POST /payments {amount: 3000000}` | 200, partial |
| 3 | `POST /payments {amount: 1500000}` | 400, `remaining_amount: 1000000` |
| 4 | `POST /payments {amount: 1000000}` | 200, `payment_status=paid` |

### 4.3 Cross-flow guards (mutual exclusion)

Start with unpaid log `L`.

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /pay {log_id: L, ...}` (legacy full pay) | 200, `is_paid=true` |
| 2 | `POST /payments {amount: 1000000}` on `L` | **400** "Bu log avval bir martalik to'lov bilan to'langan…" |
| 3 | `POST /convert-to-split` on `L` | 200, `payments[].length == 1`, `is_paid=true` |
| 4 | `POST /payments {amount: 500000}` on `L` | 400 "to'lov summasi qoldiqdan oshib ketmasligi" (remaining is 0) |
| 5 | `DELETE /payments/<id of step 3's payment>` | 200, `is_paid=false`, `paid_amount=0` |
| 6 | `POST /payments {amount: 1000000}` | 200, partial |

And the other direction:

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /payments {amount: 1000000}` on unpaid log | 200, partial |
| 2 | `POST /pay {log_id: L, ...}` | **400** "Bu logga qisman to'lovlar mavjud. Yangi to'lov uchun /overhead_type_logs/<id>/payments dan foydalaning." |

### 4.4 Delete restores partial state

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /payments {amount: 1000000}` | partial |
| 2 | `POST /payments {amount: 3000000}` | paid |
| 3 | `DELETE /payments/<id of step 2>` | `paid_amount=1M`, `remaining=3M`, `is_paid=false`, `payment_status=partial` |
| 4 | `DELETE /payments/<id of step 1>` | `paid_amount=0`, `is_paid=false`, `payment_status=unpaid` |
| 5 | `DELETE /payments/<id of step 1>` again | **400** "Allaqachon o'chirilgan" |

### 4.5 Concurrent overpayment is rejected (manual)

In two terminals against the same log (`cost=4M`, no prior payments):

```bash
# terminal A and B fire near-simultaneously
curl -X POST ".../payments" -d '{"amount": 3000000, ...}'
curl -X POST ".../payments" -d '{"amount": 3000000, ...}'
```

Expected: exactly one returns 200 with `payment_status=partial` (3M paid), the
other returns 400 with `remaining_amount: 1000000`. (Without the
`SELECT FOR UPDATE` fix this would silently allow both, overpaying by 2M.)

### 4.6 Cost update behaviour

Start with unpaid log `L` (cost = 4M).

| Step | Request | Expected |
|---|---|---|
| 1 | `PATCH /<L> {cost: 5000000}` | 200, `cost=5M`, still `unpaid` |
| 2 | `POST /payments {amount: 5000000}` | 200, `payment_status=paid` |
| 3 | `PATCH /<L> {cost: 6000000}` | 200, `cost=6M`, `is_paid=false`, `payment_status=partial`, `remaining=1M` (recomputed) |
| 4 | `PATCH /<L> {cost: 4000000}` | **400** "Yangi cost to'langan summadan kichik bo'lishi mumkin emas (5,000,000 so'm). Avval to'lovlarni o'chiring." |
| 5 | `PATCH /<L> {cost: 5000000}` | 200, `cost=5M`, back to `paid` |
| 6 | `PATCH /<L> {}` | 400 "Yangilanadigan maydonlar yo'q" |
| 7 | `PATCH /<L> {is_paid: true}` | 400 "Ruxsat etilgan maydon yo'q (faqat: cost)" |

### 4.7 Management proxy returns derived totals

```
GET /api/v1/overhead-type-logs/5/2026?location_id=3
```

Each `data[]` row contains `paid_amount`, `remaining_amount`, `payment_status`,
and `payments[]`. `summary.paid_sum` equals `Σ data[].paid_amount` — including
partial contributions. (Pre-fix it equalled `Σ data[].cost where is_paid`.)

### 4.8 Home_screen bucketing (Gennis only)

`GET /account/account_overhead_total/?month=5&year=2026&location_id=3` should
now show the rent partial payments under `total_arenda`, not `total_other`.
The simplest check: pay any partial against an "Arenda" log, then re-fetch and
confirm `total_arenda` increased by the partial amount.

---

## 5. Things to remember

- **Migrations must be applied** on Gennis and Turon servers before any new
  route works. If you call them against an un-migrated DB you'll get
  `relation "overheadtypelog_payment" does not exist` (or the Django
  equivalent).
- **Soft-delete vs hard-delete:** Payment rows are soft-deleted (`deleted=True`)
  so audit history is preserved. The accounting `Overhead` row they pointed
  to is hard-deleted on payment delete (Overhead has no `deleted` column).
- **Encashment:**
  - Gennis encashment uses `MainOverhead` (dormant on this instance — no
    integration was added; the active `Overhead`-based home_screen report
    sees split payments automatically after the bucket fix).
  - Turon encashment already aggregates `Overhead.price` directly, so split
    payments appear in encashment without any change.
- **Currency:** all amounts are integer so'm (no decimals). Frontend should
  format with thousand separators (`Intl.NumberFormat('uz-UZ')` works fine).
