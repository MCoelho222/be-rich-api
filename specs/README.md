# Be Rich: specifications

| File | Covers | Status |
|---|---|---|
| [schemas.md](schemas.md) | Data model, validation and business rules | Ready |
| [auth.md](auth.md) | Signup, login, sessions, password reset, email | Ready |
| [api.md](api.md) | HTTP endpoints, payloads, errors, pagination | Ready, except the read models in §13, which will be finalized in the dashboard planning |
| [operations.md](operations.md) | Docker deployment, jobs, configuration, backups | Ready |
| `be-rich-ui/specs/ui-behavior.md` | Forms, views and interactions (UI repository) | Ready |
| `be-rich-ui/specs/dashboard.md` | The dashboard screen, whose data contract becomes `api.md` §13 (UI repository) | Draft, being designed |

`schemas.md` is duplicated in `be-rich-ui/specs`. When it changes, update both copies. The only difference between them is the paths in the cross-repository links.
