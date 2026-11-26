# Authentication

**Scope:** this file covers signup, login, sessions, password management and transactional email.
The entities and rules it relies on (User, Household, Invitation) are defined in [schemas.md](schemas.md). Endpoint conventions (base path, error format) are defined in [api.md](api.md).

---

## 1. Approach

- Users log in with **email and password**, handled inside the FastAPI app. There is no third-party identity provider.
- Passwords are hashed with **argon2id**.
- Sessions are **stored on the server**. The browser only holds an opaque, random session token in an **httpOnly cookie**.
  - Server-side sessions can be revoked instantly. That is required when a member is removed (schemas §4.2 rule 3) and after a password reset.
- **The household is resolved on every request** from `User.household_id` in the database. It is never stored in the session or the cookie. As a result, a change of household takes effect on the user's very next request.
- **Email verification is out of scope for v1.** For invited users the invitation token already proves they own the email. For self-signups, a mistyped email only affects password reset, and the account owner can fix it in their profile.

---

## 2. Auth tables

These tables complement the entities in schemas.md.

### 2.1 Session

| Field | Type | Req. | Constraints / notes |
|---|---|---|---|
| `id` | uuid | Yes | |
| `user_id` | uuid → User | Yes | |
| `token_hash` | string | Yes | SHA-256 of the session token. **Unique.** The raw token exists only in the cookie. |
| `created_at` | timestamp | Yes | |
| `last_seen_at` | timestamp | Yes | Updated at most once per minute, to limit database writes. |
| `expires_at` | timestamp | Yes | Sliding expiry: `last_seen_at + 30 days`. |
| `absolute_expires_at` | timestamp | Yes | `created_at + 90 days`. The session never lives beyond this, even if it stays active. |
| `user_agent` | string(≤255) | No | Shown in a future "active sessions" list. |

A session is **valid** when `now < expires_at` and `now < absolute_expires_at`.

### 2.2 PasswordResetToken

| Field | Type | Req. | Constraints / notes |
|---|---|---|---|
| `id` | uuid | Yes | |
| `user_id` | uuid → User | Yes | |
| `token_hash` | string | Yes | SHA-256 of the token sent by email. **Unique.** |
| `expires_at` | timestamp | Yes | `created_at + 1 hour`. |
| `used_at` | timestamp | No | Set when the token is used. A token can be used **once**. |
| `created_at` | timestamp | Yes | |

All tokens (session, password reset and invitation) are generated with a cryptographically secure random generator and contain at least 128 bits, for example `secrets.token_urlsafe(32)`.

---

## 3. Cookies and CSRF

### 3.1 Cookies

| Cookie | Content | Flags |
|---|---|---|
| `brs_session` | The session token | `HttpOnly`, `Secure` (in production), `SameSite=Lax`, `Path=/`. Max-Age matches the absolute expiry. |
| `brs_csrf` | A random CSRF token, rotated at login | **Not** HttpOnly (the frontend has to read it), `Secure`, `SameSite=Lax`, `Path=/`. |

### 3.2 CSRF protection

- Every request that changes data (`POST`, `PUT`, `PATCH`, `DELETE`) must send an `X-CSRF-Token` header equal to the `brs_csrf` cookie. If it doesn't, the API responds **403 `CSRF_FAILED`**.
- Exempt endpoints (the user has no session yet): signup, login, password-reset request and password-reset confirm. Login rate limiting (§5) protects them instead.
- The UI and API are served **from the same origin**, behind a reverse proxy (see [operations.md](operations.md)). The cookies are therefore first-party and no CORS setup is needed.

---

## 4. Flows

All paths below are relative to `/api/v1`.

### 4.1 Signup

`POST /auth/signup`

```json
{ "name": "Marcelo Coelho", "email": "m@example.com", "password": "…", "language": "pt", "invitation_token": "…optional…" }
```

`language` (`en` or `pt`, default `en`) is the language the user sees during signup. It is stored on the User (schemas §5) and picks the language of the seed data.

**Without** `invitation_token`:

1. Validate the input (§6). The email must not be registered yet, otherwise the API responds 409 `EMAIL_TAKEN`.
2. In **one transaction**:
   - create the Household;
   - create the User;
   - create the seed data (the default expense categories and the "Cash" account, schemas §4.1).
3. Create a session, set the cookies, and respond **201** with the same body as `GET /auth/me`.

**With** `invitation_token`:

1. Look up the invitation by token hash. It must be `PENDING` and not expired, otherwise the API responds **410 `INVITATION_INVALID`**.
2. The email in the request must equal the invitation's email (the UI sends it locked), otherwise **422**.
3. In one transaction, create the User in the invitation's household and mark the invitation `ACCEPTED` (schemas §6.1 rule 5).
4. Create a session, set the cookies, and respond **201**.

### 4.2 Login

`POST /auth/login` with `{ "email": "…", "password": "…" }`

- **Success:** the API creates a new session, sets the cookies, and responds **200** with the `GET /auth/me` body.
- **Failure:** the API responds **401 `INVALID_CREDENTIALS`** with the message "Invalid email or password". The response is the same whether or not the email exists.
- **Timing:** a password hash is computed even when the email doesn't exist, so response times don't reveal which emails are registered.

### 4.3 Logout

`POST /auth/logout` deletes the current session, clears both cookies, and responds **204**.

### 4.4 Current user

`GET /auth/me` returns **200** with this body:

```json
{
  "user": { "id": "…", "name": "…", "email": "…", "household_id": "…", "language": "en", "avatar": null },
  "household": { "id": "…", "name": "…", "default_currency": "BRL" }
}
```

Without a valid session it responds **401 `UNAUTHENTICATED`**.

### 4.5 Change password (logged in)

`POST /auth/password` with `{ "current_password": "…", "new_password": "…" }`

- If the current password is wrong, the API responds **401 `INVALID_CREDENTIALS`**.
- On success, **every other session** of the user is deleted, and the current session stays.

### 4.6 Password reset

1. **Request:** `POST /auth/password-reset/request` with `{ "email": "…" }`
   - The API **always** responds **202**, whether or not the email exists.
   - If the email belongs to a user, it creates a PasswordResetToken and sends the email `<APP_URL>/reset-password/<token>`.
   - Requesting a reset invalidates any earlier unused tokens for that user.
2. **Confirm:** `POST /auth/password-reset/confirm` with `{ "token": "…", "new_password": "…" }`
   - The token must be unused and not expired, otherwise the API responds **410 `TOKEN_INVALID`**.
   - On success, the API sets the new password, marks the token as used, **deletes every session** of the user, and responds **204**. The user then logs in again.

### 4.7 Invitation lookup (public)

`GET /invitations/lookup?token=…`

- **Valid invitation:** the API responds **200** with `{ "household_name": "…", "email": "…", "invited_by_name": "…" }`, which the signup page uses to show "Join Marcelo's household".
- **Not valid:** **410 `INVITATION_INVALID`**. The response does not say why the invitation is invalid.

### 4.8 Ending sessions on household changes

- **A member is removed:** all of that user's sessions are deleted (schemas §4.2 rule 3). They log in again and land in their new household.
- **A member leaves:** the user's sessions are kept. Since the household is resolved on each request (§1), the next request already shows the new household.

---

## 5. Rate limiting

| Endpoint | Limit | Response when exceeded |
|---|---|---|
| `POST /auth/login` | 5 failures per email per 15 min, and 20 failures per IP per 15 min | 429 `RATE_LIMITED`, with a `Retry-After` header |
| `POST /auth/password-reset/request` | 3 per email per hour, and 10 per IP per hour | Still 202 (silently dropped), to avoid revealing whether the email exists |
| `POST /auth/signup` | 10 per IP per hour | 429 |
| `POST /invitations`, resend | 20 per household per day | 429 |

Counters are kept in Postgres in v1, since the scale is a single VPS. Use Redis instead if the API ever runs on more than one host.

---

## 6. Password rules

These follow NIST SP 800-63B:

- **Length:** at least **8** characters and at most **128**. Every Unicode character is allowed, including spaces.
- **No composition rules:** passwords don't have to mix uppercase letters, digits or symbols.
- **Rejected passwords:** passwords equal to the email address or the user's name. *Optional:* also reject the 10,000 most common passwords, using a bundled list.
- **Hashing:** argon2id with the library defaults (for example `argon2-cffi`). Rehash at login whenever the parameters change.

---

## 7. Transactional email

- **Provider:** **Resend**, behind an `EmailSender` interface so it can be swapped for SES or SMTP.
- **In development**, emails go to a **Mailpit** container (an SMTP inbox that can be viewed in the browser). See operations.md.
- **Sender:** `EMAIL_FROM`, for example `Be Rich <no-reply@your-domain>`. The domain needs SPF, DKIM and DMARC configured.
- **Sending:** emails are sent **after** the database transaction commits. A failed send is logged and returned as **502 `EMAIL_FAILED`** for invitations, so the UI can offer "Resend". For password reset the failure is only logged, and the response is still 202.

### 7.1 Templates

Each template has a pt-BR plain-text version and an HTML version.

| Template | Variables | Link |
|---|---|---|
| `invitation` | inviter name, household name, expiry date | `<APP_URL>/invite/<token>` |
| `password_reset` | user's first name | `<APP_URL>/reset-password/<token>` |
| `password_changed` | user's first name, time of the change | none ("If this wasn't you, reset your password") |
