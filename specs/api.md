# API Contract

**Scope:** this file covers the HTTP endpoints, payloads, errors and pagination.
Entities, validation rules and business rules are defined in [schemas.md](schemas.md), and section references (§) point to that file unless stated otherwise. Authentication endpoints are defined in [auth.md](auth.md).

> **Status:** the write side and the reference resources are complete. The read models in §13 are a **draft** that will be finalized while planning the dashboard.

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

Account balances are read models, see §12.

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

The form preview (ui-behavior §6.2) uses this endpoint, so the date and rounding rules exist only on the server. If the currency is not the household default, the response also includes `converted_total`, a money object at the latest rate.

### 10.6 Update

`PATCH /expenses/{id}?scope=THIS|THIS_AND_FOLLOWING|ALL`

- `scope` is **required** when the row has an `installment_group_id`, otherwise the API responds 422 `SCOPE_REQUIRED`. For other rows it is ignored.
- **Accepted body fields:**
  - any of `spender_id`, `category_id`, `description` and `amount`;
  - with `scope=ALL` only: `transaction_date`, `payment_method`, `card_id`, `account_id`, `currency` and `installments` (§10.6). Sending one of these with another scope responds 422.
- **With `scope=ALL`**, `amount` is the **new total**, and the series is regenerated whenever an `ALL`-only field changes.
- **Changing payment fields on a single, non-series row** (method, card, account or currency) is also allowed. Its `payment_date` is recalculated.
- **Response 200:** `{ "items": [Expense, …] }`, containing every affected row after the update.

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
| `POST /recurrences` | The Recurrence fields (schemas §12), plus an optional `register_first: { occurrence_date, amount?, description? }` | 201 `{ recurrence, registered: Expense \| Income \| null }` |
| `PATCH /recurrences/{id}` | Any field except `type` | Recurrence. Only affects unregistered occurrences (§12.3). |
| `POST /recurrences/{id}/pause` and `/resume` | | Recurrence |
| `POST /recurrences/{id}/end` | `{ end_date }` (default today) | Recurrence |
| `POST /recurrences/{id}/change-amount` | `{ effective_date, amount }` | `{ ended: Recurrence, created: Recurrence }` |
| `DELETE /recurrences/{id}` | | 204, or 409 `IN_USE` when it has registered rows |

### 12.2 Details

- **`register_first`** creates the Recurrence and its first registered row in **one transaction**. This is the "Repeats" toggle in the entry forms (ui-behavior §6.4).
- **`next_occurrence`** has the shape `{ occurrence_date, payment_date, status }`, or null.
- **`change-amount`** ends the current Recurrence on `effective_date − 1 day` and creates a copy starting on `effective_date` (§12.3).

### 12.3 Occurrences

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /recurrences/{id}/occurrences` | `from`, `to` | `{ items: [Occurrence] }` |
| `POST /recurrences/{id}/occurrences/{occurrence_date}/register` | Optional overrides: `amount`, `transaction_date`, `description`, `account_id`, `card_id`, `person_id` | 201 Expense or Income. Responds 409 `CONFLICT` if the occurrence is already registered, and 422 if a reference is archived or the person is a former member (§12.2, §4.2 rule 6). |
| `POST /recurrences/{id}/occurrences/{occurrence_date}/skip` | | 204 |
| `DELETE /recurrences/{id}/occurrences/{occurrence_date}/skip` | | 204 (undoes the skip) |
| `GET /occurrences/overdue` | | `{ items: [Occurrence + recurrence_id] }` across the whole household, oldest first |

The Occurrence shape:

```json
{ "occurrence_date": "2026-12-05", "payment_date": "2026-12-07", "expected_amount": "120.00",
  "currency": "BRL", "status": "REGISTERED|PENDING|OVERDUE|FUTURE|SKIPPED", "row_id": "…|null" }
```

`occurrence_date` in a path must be a real occurrence date of that Recurrence, otherwise the API responds 404.

---

## 13. Read models (DRAFT, to be finalized in dashboard planning)

These endpoints compute the read models but never store them. All amounts are converted to the household's `default_currency` (§15–§16). Every response includes:

```json
{ "currency": "BRL", "rates_as_of": "2026-11-19", "unconverted": [] }
```

| Method & path | Query | Purpose |
|---|---|---|
| `GET /balances` | `date` (default today), `include_archived` (default true) | The per-account `balance(a, t)` and the household total (§14). |
| `GET /projection` | `from`, `to`, `granularity=month`, `account_id` (optional) | Per month: realized and projected income and expenses, net result, and the end-of-month balance (§13–§14). |
| `GET /projection/items` | `from`, `to`, `account_id`, `type`, `limit`, `cursor` | The stored rows plus the projected occurrences in one list, each marked `projected: true\|false` (ui-behavior §9.4). |
| `GET /dashboard/summary` | `from`, `to` | The values for the summary cards (ui-behavior §9.2). |

## 14. Exchange rates

| Method & path | Query | Returns |
|---|---|---|
| `GET /exchange-rates/latest` | `base` (default: household currency) | `{ base, rate_date, rates: { "USD": "0.18350000", … } }` |
