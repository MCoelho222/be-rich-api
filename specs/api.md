# API Contract

**Scope:** this file covers the HTTP endpoints, payloads, errors and pagination.
Entities, validation rules and business rules are defined in [schemas.md](schemas.md), and section references (§) point to that file unless stated otherwise. Authentication endpoints are defined in [auth.md](auth.md).

> **Status:** complete.

---

## 1. Conventions

### 1.1 Requests and responses

- **Base path:** `/api/v1`. The API is served from the same origin as the UI (see [operations.md](operations.md)).
- **Format:** JSON bodies with `snake_case` keys.
- **Dates and timestamps:** dates use `YYYY-MM-DD`, and timestamps use ISO 8601 in UTC with a `Z` suffix.
- **Money is sent as a decimal string with exactly 2 decimal places**, such as `"1234.50"`, never as a JSON number. This avoids floating-point errors in clients. Exchange rates are strings with up to 8 decimal places.
- **Money fields always travel with their currency**, either as a sibling `currency` field or as a money object: `{ "amount": "1234.50", "currency": "BRL" }`.
- **IDs** are UUID strings.

### 1.2 Authentication and household scope

- Requests are authenticated with the session cookie (auth.md). Requests that change data also need the `X-CSRF-Token` header.
- **Every resource is scoped to the caller's current household.** An ID that belongs to another household returns **404**, not 403, so that other households' data can't be detected.

### 1.3 Writes

- **Creates** return **201** with the created resource or resources.
- **Updates** use `PATCH` with partial bodies and return **200** with the updated resource. Fields that are not sent are left unchanged.
- **Deletes** return **204**.
- **Concurrent edits:** the last write wins in v1. Every resource returns `updated_at`, so optimistic locking can be added later without breaking changes.

### 1.4 References and archiving

- **References are returned as IDs.** The client keeps the small reference lists (members, accounts, cards and categories) and looks names up locally.
- **Archiving** is done through the `/archive` and `/unarchive` sub-resources. `DELETE` on an in-use record returns **409 `IN_USE`** (§18).

---

## 2. Errors

Every error returns the same envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Some fields are invalid.",
    "fields": { "amount": ["Must be greater than zero"], "parts[1].card_id": ["Card does not support debit"] }
  }
}
```

`fields` is only present for validation errors. Its keys are field paths, using dot and index notation for nested values.

| HTTP | `code` | When |
|---|---|---|
| 400 | `BAD_REQUEST` | The JSON is malformed, or a query parameter is unknown. |
| 401 | `UNAUTHENTICATED` | There is no session, or the session is invalid. |
| 401 | `INVALID_CREDENTIALS` | Login or password change failed. |
| 403 | `CSRF_FAILED` | The CSRF header is missing or doesn't match. |
| 404 | `NOT_FOUND` | The resource doesn't exist or belongs to another household. |
| 409 | `CONFLICT` | A uniqueness rule was violated (a name, an email, an already registered occurrence). |
| 409 | `IN_USE` | A delete was blocked because the record is referenced (§18). The response also includes `"usage": { "expenses": 14, "incomes": 0, "recurrences": 1 }`. |
| 409 | `LAST_MEMBER` | The last member tried to leave or be removed (§4.2). |
| 410 | `INVITATION_INVALID` / `TOKEN_INVALID` | An invitation or reset token is expired, used or revoked. |
| 422 | `VALIDATION_ERROR` | A field or business rule was violated. |
| 422 | `SCOPE_REQUIRED` | The row belongs to an installment series and no `scope` was given (§10.6). |
| 429 | `RATE_LIMITED` | Too many requests. A `Retry-After` header is included. |
| 502 | `EMAIL_FAILED` | The email provider failed (auth.md §7). |

---

## 3. Pagination and filtering

- **Lists that can grow** (expenses, incomes) use **cursor pagination**:
  - Query parameters: `limit` (default 50, maximum 200) and `cursor`, an opaque string.
  - Response shape: `{ "items": [...], "next_cursor": "…" | null }`.
  - Default order: `payment_date` descending, then `created_at` descending, then `id`.
- **Reference lists** (members, accounts, cards, categories, recurrences, invitations) are returned **unpaginated** as `{ "items": [...] }`.
- **Date ranges** are inclusive on both ends: `from=2026-12-01&to=2026-12-31`.

---

## 4. Household and members

| Method & path | Body / query | Returns | Notes |
|---|---|---|---|
| `GET /household` | | Household | |
| `PATCH /household` | `name`, `default_currency` | Household | |
| `GET /household/members` | | `{ items: [{ id, name, email, is_you }] }` | Current members only. |
| `DELETE /household/members/{user_id}` | | 204 | Removes a member (§4.2) and ends their sessions. Responds 409 `LAST_MEMBER` when needed. Removing yourself responds 422; use `/leave` instead. A user outside the household responds 404. |
| `POST /household/leave` | | 200 with the `GET /auth/me` body | The caller moves to a new household (§4.2). |
| `GET /users/{id}` | | `{ id, name, is_current_member }` | Resolves the names of **former members** that are referenced by rows (§4.2 rule 4). |

## 5. Profile

| Method & path | Body | Returns |
|---|---|---|
| `GET /me` | | User (without `password_hash`) |
| `PATCH /me` | `name`, `email`, `cpf`, `birth_date`, `phone`, `address`, `notes` | User |

Changing `email` responds 409 `CONFLICT` when the new address is already registered.

## 6. Invitations

| Method & path | Body | Returns |
|---|---|---|
| `GET /invitations` | | `{ items: [Invitation] }` with `PENDING` invitations only |
| `POST /invitations` | `{ email }` | 201 Invitation. Responds 422 when the email already has an account (§6.1 rule 6), 409 `CONFLICT` when an invitation to that email is already pending (use resend), or 502 `EMAIL_FAILED` (the invitation is kept, so the UI can offer Resend) |
| `POST /invitations/{id}/resend` | | 201 with the new Invitation (the old one becomes `REVOKED`) |
| `POST /invitations/{id}/revoke` | | 204 |
| `GET /invitations/lookup?token=` | | Public, see auth.md §4.7 |

The Invitation response contains `id`, `email`, `status`, `invited_by_id`, `expires_at` and `created_at`. It **never includes the token**.

## 7. Accounts

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /accounts` | `include_archived` (default false) | `{ items: [Account] }` |
| `POST /accounts` | `type`, `name`, `currency`, `opening_balance`, `opening_balance_date` | 201 Account |
| `PATCH /accounts/{id}` | `name`, `currency`, `opening_balance`, `opening_balance_date` | Account (`type` cannot be changed) |
| `POST /accounts/{id}/adjust` | `{ balance, date }` (default `date` is today) | Account. Sets the opening balance and its date (§14.3). |
| `POST /accounts/{id}/archive` | | Account. Responds 422 when it is the last active `CASH` account. |
| `POST /accounts/{id}/unarchive` | | Account |
| `DELETE /accounts/{id}` | | 204, or 409 `IN_USE` |

Account balances are read models, see §13.2.

## 8. Cards

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /cards` | `include_archived` | `{ items: [Card] }` |
| `POST /cards` | `owner_id`, `alias`, `type`, `account_id`, `last_four`, `best_buy_day`, `due_day` | 201 Card |
| `PATCH /cards/{id}` | Any of the same fields | Card |
| `POST /cards/{id}/archive` and `/unarchive` | | Card. Unarchiving requires an owner who is a current member (§4.2 rule 5). |
| `DELETE /cards/{id}` | | 204, or 409 `IN_USE` |
| `POST /cards/preview` | `{ best_buy_day, due_day, purchase_date }` | `{ closing_date, payment_date }`. Used for the live preview in the card form before the card exists. The server applies holidays. |

## 9. Categories

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /categories` | `type` (required), `include_archived` | `{ items: [Category] }` |
| `POST /categories` | `type`, `name` | 201 Category |
| `PATCH /categories/{id}` | `name` | Category |
| `POST /categories/{id}/archive` and `/unarchive` | | Category |
| `DELETE /categories/{id}` | | 204, or 409 `IN_USE` |

---

## 10. Expenses

### 10.1 The Expense row (response)

```json
{
  "id": "…", "spender_id": "…", "transaction_date": "2026-11-20", "payment_date": "2026-12-07",
  "amount": "33.34", "currency": "BRL", "payment_method": "CREDIT",
  "card_id": "…", "account_id": "…", "category_id": "…", "description": "Headphones",
  "installment_number": 1, "installment_total": 3, "installment_group_id": "…",
  "split_group_id": null, "recurrence_id": null, "occurrence_date": null,
  "created_by_id": "…", "created_at": "…", "updated_at": "…"
}
```

### 10.2 List

`GET /expenses` accepts the following query parameters, all optional:

| Parameter | Meaning |
|---|---|
| `from`, `to` | Date range. |
| `date_field` | `payment_date` (the default) or `transaction_date`. |
| `account_id`, `card_id`, `category_id`, `spender_id` | Filter by reference. |
| `payment_method` | Filter by method. |
| `recurrence_id` | Filter to rows registered from one Recurrence. |
| `fixed_only` | Only rows registered from any Recurrence. |
| `installment_group_id`, `split_group_id` | Filter to one series or one split purchase. |
| `q` | Case-insensitive search in `description`. |
| `limit`, `cursor` | Pagination (§3). |

The response is paginated: `{ items: [Expense], next_cursor }`.

### 10.3 Get

`GET /expenses/{id}` returns the Expense.

### 10.4 Create

`POST /expenses` creates the rows for **one purchase**:

```json
{
  "transaction_date": "2026-11-20",
  "currency": "BRL",
  "category_id": "…",
  "spender_id": "…",
  "description": "Headphones",
  "total_amount": "150.00",
  "parts": [
    { "payment_method": "PIX", "account_id": "…", "amount": "50.00" },
    { "payment_method": "CREDIT", "card_id": "…", "amount": "100.00", "installments": 3 }
  ]
}
```

- **`parts`** must contain 1 to 6 parts.
- **With exactly 1 part**, the part's `amount` is optional and defaults to `total_amount`, and no `split_group_id` is created.
- **With 2 or more parts**, every part needs an `amount`, and the amounts must add up to `total_amount` (§10.5).
- **`installments`** defaults to 1.
- **`account_id`** rules come from §10:
  - for `CREDIT` and `DEBIT` it is ignored, because the card's account is used;
  - for `CASH` it is optional and defaults to the first active cash account;
  - for every other method it is required.
- **`spender_id`** defaults to the caller. **`transaction_date`** defaults to today, and **`currency`** to the household's default.
- **Response 201:** `{ "split_group_id": "…" | null, "items": [Expense, …] }`. Rows are ordered by part, then by `installment_number`.

### 10.5 Preview

`POST /expenses/preview` takes **the same body** as create and returns the rows that **would** be created, with no `id`s and **nothing saved**. Validation errors are returned in the same shape as for create.

The response is `{ "items": [PlannedRow, …], "converted_total": Money | null }`. A PlannedRow has `part` (the index in `parts`), the dates, `amount`, `currency`, `payment_method`, `card_id`, `account_id`, `installment_number` and `installment_total`, but no ids or group ids.

The form preview (ui-behavior §6.2) uses this endpoint, so the date and rounding rules exist only on the server. If the currency is not the household default, the response also includes `converted_total`, a money object at the latest rate.

### 10.6 Update

`PATCH /expenses/{id}?scope=THIS|THIS_AND_FOLLOWING|ALL`

- `scope` is **required** when the row has an `installment_group_id`, otherwise the API responds 422 `SCOPE_REQUIRED`. For other rows it is ignored.
- **Accepted body fields:**
  - any of `spender_id`, `category_id`, `description` and `amount`;
  - with `scope=ALL` only: `transaction_date`, `payment_method`, `card_id`, `account_id`, `currency` and `installments` (§10.6). Sending one of these with another scope responds 422.
- **With `scope=ALL`**, `amount` is the **new total**, and the series is regenerated whenever an `ALL`-only field changes.
- **Changing payment fields on a single, non-series row** (method, card, account or currency) is also allowed. Its `payment_date` is recalculated.
- **Purchase-level fields in a split purchase:** `spender_id`, `category_id` and `description` are applied to every row of the split purchase, whatever the scope, and so are `transaction_date` and `currency` (the other parts get their payment dates recalculated). This keeps the rule in schemas §10.5 that all parts share them.
- **Response 200:** `{ "items": [Expense, …] }`, containing every row of the edited series, or of the whole split purchase, after the update. Row ids are kept when a series is regenerated; only added installments get new ids.

### 10.7 Delete

`DELETE /expenses/{id}?scope=…` follows the same `scope` rule and returns **204**.

---

## 11. Incomes

The `/incomes` endpoints mirror §10 exactly:

| Endpoint | Shape |
|---|---|
| `GET /incomes` | Filters: `receiver_id` instead of `spender_id`, and no `card_id`. |
| `GET /incomes/{id}` | |
| `POST /incomes` | Uses `receiver_id`. Parts have `payment_method`, `account_id`, `amount` and `installments`, with no `card_id`. |
| `POST /incomes/preview` | |
| `PATCH /incomes/{id}?scope=` | |
| `DELETE /incomes/{id}?scope=` | |

The income rules are in schemas §11.

---

## 12. Recurrences

### 12.1 Endpoints

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /recurrences` | `type`, `status=active\|paused\|ended\|all` (default `active`) | `{ items: [Recurrence + next_occurrence] }` |
| `GET /recurrences/{id}` | | Recurrence |
| `POST /recurrences` | The Recurrence fields (schemas §12), plus an optional `register_first: { occurrence_date, transaction_date?, amount?, description? }` | 201 `{ recurrence, registered: Expense \| Income \| null }` |
| `PATCH /recurrences/{id}` | Any field except `type` | Recurrence. Only affects unregistered occurrences (§12.3). |
| `POST /recurrences/{id}/pause` and `/resume` | | Recurrence |
| `POST /recurrences/{id}/end` | `{ end_date }` (default today) | Recurrence |
| `POST /recurrences/{id}/change-amount` | `{ effective_date, amount }` | `{ ended: Recurrence, created: Recurrence }` |
| `DELETE /recurrences/{id}` | | 204, or 409 `IN_USE` when it has registered rows |

### 12.2 Details

- **`register_first`** creates the Recurrence and its first registered row in **one transaction**. This is the "Repeats" toggle in the entry forms (ui-behavior §6.4). `transaction_date` defaults as in the register endpoint (§12.3).
- **`next_occurrence`** has the shape `{ occurrence_date, payment_date, status }`, or null.
- **`change-amount`** ends the current Recurrence on `effective_date − 1 day` and creates a copy starting on `effective_date` (§12.3). Payments already registered for occurrences on or after `effective_date` move to the copy, so they aren't shown as unpaid there. `effective_date` must be after `start_date` (otherwise edit the amount) and not after `end_date`.
- **`status`** is computed: `ENDED` when `end_date` is before today, `PAUSED` when `is_active` is false, otherwise `ACTIVE`. The `status` query parameter filters on it.
- **`next_occurrence`** is the first unregistered, non-skipped occurrence from the current month on. It is null for paused or ended recurrences.

### 12.3 Occurrences

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /recurrences/{id}/occurrences` | `from`, `to` | `{ items: [Occurrence] }` |
| `POST /recurrences/{id}/occurrences/{occurrence_date}/register` | Optional overrides: `amount`, `transaction_date` (default: the occurrence date; for a credit card fixed expense, a purchase date inside the bill due that day, schemas §12.1), `description`, `account_id`, `card_id`, `person_id` | 201 Expense or Income. Responds 409 `CONFLICT` if the occurrence is already registered, and 422 if a reference is archived or the person is a former member (§12.2, §4.2 rule 6). |
| `POST /recurrences/{id}/occurrences/{occurrence_date}/skip` | | 204 |
| `DELETE /recurrences/{id}/occurrences/{occurrence_date}/skip` | | 204 (undoes the skip) |
| `GET /occurrences/overdue` | | `{ items: [Occurrence + recurrence_id] }` across the whole household, oldest first |

The Occurrence shape:

```json
{ "occurrence_date": "2026-12-05", "payment_date": "2026-12-07", "expected_amount": "120.00",
  "currency": "BRL", "status": "REGISTERED|PENDING|OVERDUE|FUTURE|SKIPPED", "row_id": "…|null" }
```

`occurrence_date` in a path must be a real occurrence date of that Recurrence, otherwise the API responds 404.

- `GET …/occurrences` defaults to the current month and the following 11.
- Registering a **skipped** occurrence responds 409 (undo the skip first). Skipping a **registered** occurrence also responds 409 (delete the payment first).
- A **paused** recurrence can still have occurrences registered, since that records a payment that really happened. Its occurrences never appear in `/occurrences/overdue`, which only covers active recurrences.

---

## 13. Read models

These endpoints compute their results on every request and never store them. They serve the dashboard (`be-rich-ui/specs/dashboard.md`) and can be used by any other view.

### 13.1 Shared rules

**Query parameters.** Unless an endpoint says otherwise:

| Parameter | Meaning |
|---|---|
| `from`, `to` | Required. Inclusive date range, filtered on `payment_date` (§3). `to` must not be before `from`, and the range is at most 3 years (1,096 days); otherwise 422 `VALIDATION_ERROR`. |
| `account_id` | Optional. Only rows and occurrences with this `account_id`, and only this account's balance. |
| `member_id` | Optional. Only expenses with this `spender_id`, incomes with this `receiver_id`, and occurrences with this `person_id`. It never filters balances, because account money belongs to the household. A former member's ID is accepted. |

An unknown `account_id` or `member_id` returns 404 (§1.2).

**Conversion.** Every amount is converted to the household's `default_currency` using the rates in schemas §16.3, and summed as in schemas §15. Every response carries this block at the top level:

```json
{ "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [{ "currency": "USD", "amount": "12.00" }] }
```

- `rates_as_of` is the date of the oldest rate used, or null when no conversion was needed.
- `unconverted` lists, per currency, the amounts left out of every total because no rate was ever cached (schemas §16.4). It is usually empty.

**What counts.** "Stored rows" are Expense and Income rows. "Projected occurrences" are the valid, unregistered, non-overdue occurrences of schemas §13.1, with their amount from the Recurrence. Overdue occurrences are never counted here; they come from `GET /occurrences/overdue` (§12.3).

**Realized and total.** Amounts that can include the future are returned as a pair:

- `realized`: stored rows with `payment_date` ≤ min(`to`, today);
- `total`: every stored row in the range plus projected occurrences (schemas §13.1).

For a range entirely in the past, `realized` equals `total`. The response flag `includes_projection` is true when `to` ≥ today.

### 13.2 Balances

`GET /balances?date=&account_id=`

| Parameter | Default | Meaning |
|---|---|---|
| `date` | today | The balance at the end of this day (schemas §14.1). After today it is a projected balance. |
| `account_id` | | Only this account. |
| `include_archived` | `true` | Archived accounts still hold money, so they count by default. |

```json
{
  "date": "2026-12-31", "projected": true,
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "total": "12450.32",
  "accounts": [
    { "account_id": "…", "account_currency": "BRL", "balance": "1200.00", "converted": "1200.00" },
    { "account_id": "…", "account_currency": "USD", "balance": null, "converted": null }
  ]
}
```

- `balance` is in the account's own currency; `converted` is in `default_currency`.
- Both are null when `date` is before the account's `opening_balance_date`. That account is left out of `total`.
- `projected` is true when `date` is after today.
- When no rate has ever been cached for an account's currency, its `converted` is null and its balance is listed in `unconverted` instead of being added to `total`.
- `member_id` is ignored here (§13.1).

### 13.3 Dashboard summary

`GET /dashboard/summary?from=&to=&account_id=&member_id=`

```json
{
  "from": "2026-11-01", "to": "2026-11-30", "includes_projection": true,
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "income":   { "realized": "3100.00", "total": "5400.00" },
  "expenses": { "realized": "2650.10", "total": "4980.75" },
  "net":      { "realized": "449.90",  "total": "419.25" },
  "fixed_expenses": { "total": "2096.90", "share": "0.4210" }
}
```

- `net` = `income` − `expenses`, for each of `realized` and `total` (schemas §13.3).
- `fixed_expenses.total` is the expense rows with a `recurrence_id` plus projected expense occurrences in the range.
- `fixed_expenses.share` = `fixed_expenses.total` ÷ `expenses.total`, as a decimal string with 4 places, or null when `expenses.total` is zero.

### 13.4 Projection

`GET /projection?from=&to=&account_id=&member_id=`

`from` is moved back to the first day of its month and `to` forward to the last day of its month. The range is at most 36 months.

```json
{
  "from": "2026-11-01", "to": "2027-04-30",
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "months": [
    {
      "month": "2026-11",
      "income":   { "realized": "3100.00", "scheduled": "0.00",   "projected_fixed": "2300.00", "total": "5400.00" },
      "expenses": { "realized": "2650.10", "scheduled": "980.00", "projected_fixed": "1350.65", "total": "4980.75" },
      "net": "419.25",
      "end_balance": "12869.57", "end_balance_projected": true
    }
  ],
  "first_negative_month": "2027-03"
}
```

- Per month and type: `realized` is stored rows paid up to today, `scheduled` is stored rows with a later `payment_date` (installments and other future-dated rows), and `projected_fixed` is projected occurrences. `total` is their sum.
- `end_balance` is the household total balance (§13.2) on the month's last day; with `account_id`, that account's balance. It ignores `member_id`. It is null when no included account has an opening balance by that date.
- `end_balance_projected` is true when the month's last day is after today.
- `first_negative_month` is the first month, from the current month on, whose `end_balance` is below zero, or null.

### 13.5 Category breakdown

`GET /dashboard/categories?from=&to=&type=&account_id=&member_id=`

`type` is `EXPENSE` (the default) or `INCOME`.

```json
{
  "type": "EXPENSE", "from": "2026-11-01", "to": "2026-11-30",
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "total": "4980.75",
  "items": [
    { "category_id": "…", "realized": "1200.00", "total": "1850.00", "share": "0.3714" }
  ]
}
```

- Only categories with at least one stored row or projected occurrence in the range appear. Archived categories appear when they are used.
- Sorted by `total` descending, then by category name.
- `share` = the item's `total` ÷ the response `total`, with 4 decimal places.

### 13.6 Card bills

`GET /cards/bills?account_id=&member_id=`

There are no `from`/`to` parameters: each card's **next bill** is the first statement whose due date (after the business-day shift, schemas §17) is today or later.

```json
{
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "items": [
    {
      "card_id": "…", "due_date": "2026-12-07", "closes_on": "2026-11-26",
      "rows_total": "1100.00", "projected_fixed": "140.00", "total": "1240.00", "rows_count": 7
    }
  ]
}
```

- One item per active card of type `CREDIT` or `CREDIT_DEBIT`, ordered by `due_date`, then card name. A card with nothing on the bill still appears, with zero totals.
- `rows_total` is the `CREDIT` expense rows with that `card_id` and `payment_date` = `due_date`. `projected_fixed` is the projected occurrences of `CREDIT` recurrences on that card with that payment date. `total` is their sum.
- `closes_on` is the last purchase date that falls on this bill: the day before `best_buy_day` in the statement's closing month (schemas §10.3).
- With `account_id`, only cards that pay from that account are included.

### 13.7 Projection items

`GET /projection/items?from=&to=&type=&account_id=&member_id=&order=&limit=&cursor=`

The stored rows and projected occurrences of the range in one paginated list (§3). `type` is `EXPENSE`, `INCOME`, or omitted for both. `order` is `desc` (the default) or `asc`, on `payment_date`, then `created_at` (occurrences sort after stored rows on the same date), then `id` or `recurrence_id`.

```json
{
  "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [],
  "items": [
    {
      "type": "EXPENSE", "projected": false, "payment_date": "2026-11-18",
      "amount": "33.34", "currency": "BRL", "converted": "33.34",
      "row": { "…": "the Expense row of §10.1" }, "occurrence": null
    },
    {
      "type": "INCOME", "projected": true, "payment_date": "2026-11-28",
      "amount": "2300.00", "currency": "BRL", "converted": "2300.00",
      "row": null,
      "occurrence": {
        "recurrence_id": "…", "occurrence_date": "2026-11-28", "status": "FUTURE",
        "description": "Salary", "category_id": "…", "account_id": "…", "card_id": null,
        "person_id": "…", "payment_method": "PIX"
      }
    }
  ],
  "next_cursor": null
}
```

- Exactly one of `row` and `occurrence` is set. `occurrence.status` is `PENDING` or `FUTURE`.
- `converted` is in `default_currency`, or null when the currency has no rate (it is then counted in `unconverted`).
- Pending occurrences whose payment date has passed are placed on today (schemas §13.1).

---

## 14. Exchange rates

| Method & path | Query | Returns |
|---|---|---|
| `GET /exchange-rates/latest` | `base` (default: household currency) | `{ base, rate_date, rates: { "USD": "0.18350000", … } }` |
