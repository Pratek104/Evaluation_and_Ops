# Architecture

## Overview

The portal is a Streamlit application with a small domain layer underneath the
UI. Streamlit page scripts are intentionally thin; business logic lives in
`src/xyz_portal/` so it can be tested without a browser.

```text
streamlit_app.py / app.py
          │
          ▼
src/xyz_portal/ui/app.py
          │
          ├── auth.ensure_database()
          ├── session.get_session_user()
          ├── login.render_login()                 (unauthenticated)
          └── st.navigation(build_pages(user))     (authenticated)
                    │
                    ▼
              app_pages/*.py
                    │
                    ▼
          xyz_portal.ui.pages.*.render(user)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  auth service              rag engine / chat
  (SQLite + RBAC)           (scoped retrieval + LLM)
```

## Layers

### `xyz_portal.config`

Loads `.env` once, resolves project-relative paths, and exposes runtime
configuration. All relative paths are resolved against the project root so the
app behaves the same regardless of the shell's working directory.

### `xyz_portal.auth`

- `constants.py` — static RBAC policy and the 15 seeded employee records.
- `passwords.py` — salted PBKDF2-SHA256 hashing and constant-time verification.
- `database.py` — schema, connection/transaction handling, row-to-user mapping,
  and idempotent seeding.
- `service.py` — authentication, session reload, permission checks, directory and
  compensation queries, role matrix, and audit reads.

The service layer accepts an optional `db_path`, which keeps it testable with
temporary databases. UI code uses the configured default.

### `xyz_portal.rag`

- `engine.py` — PDF extraction, text cleaning, chunking, hybrid retrieval, and
  pre-ranking access filtering.
- `openrouter.py` — streaming OpenRouter client with free-model fallback and
  user-facing error messages.
- `tracing.py` — LangSmith setup with no-op fallbacks when tracing is disabled or
  unavailable.

### `xyz_portal.chat`

Builds retrieval queries from short follow-ups and assembles the grounded system
prompt. The prompt includes the signed-in employee's role and handbook scope but
never includes data the role cannot retrieve.

### `xyz_portal.ui`

- `app.py` — page configuration, database bootstrap, authentication gate, and
  navigation.
- `session.py` — session reload, role-change detection, logout, and page guards.
- `login.py` — sign-in form and demo account guidance.
- `navigation.py` — role-aware page registry and sidebar account card.
- `components.py` — reusable chat rendering.
- `pages/` — page render functions with repeated authorization checks.

`app_pages/` contains only one-line scripts that import a render function and
the session guard. This keeps Streamlit's multipage discovery simple while
keeping implementation in the package.

## Request lifecycle

1. `streamlit_app.py` adds `src/` to `sys.path` and calls `ui.app.run()`.
2. `run()` configures the page, ensures the database exists, and reloads the
   signed-in user from SQLite.
3. If no valid session exists, the login form is rendered.
4. Otherwise, `build_pages(user)` registers only the pages the role may use, and
   `st.navigation(...).run()` executes the selected page.
5. The page calls `require_user()` and its render function. The render function
   repeats the authorization check before querying data.

## RBAC enforcement points

The app treats navigation as presentation, not security.

| Layer | Enforcement |
| --- | --- |
| Navigation | Hides pages the role cannot use |
| Page render | Rechecks the required permission |
| Data service | Filters directory and salary SQL rows by permission |
| Retrieval | Marks restricted passages ineligible before ranking |
| Prompt | States the user's role and allowed handbook scope |
| Session | Clears chat history when role or permissions change |

The database schema also uses foreign keys from `role_permissions` to `roles` and
`permissions`, and `employees.role` to `roles`.

## Retrieval pipeline

1. Extract text page by page from the handbook PDF.
2. Normalize PDF artifacts and drop table-of-contents dot leaders.
3. Split text into overlapping sentence-boundary chunks.
4. Classify each chunk as `public`, `directory`, or `salary`.
5. Build a BM25 index and, when available, local MiniLM embeddings.
6. For a query, filter chunks by the user's scope (`public`, `directory`, or
   `full`).
7. Rank allowed chunks with a weighted combination of semantic and keyword
   scores.
8. Send only the top allowed passages to OpenRouter.
9. Persist the answer with source pages and relevance scores.

Embeddings are cached by PDF fingerprint plus model/chunk settings, so a changed
PDF invalidates the cache automatically. If the embedding model cannot load,
retrieval falls back to BM25 keyword search.

## Tracing

When LangSmith is configured, each chat turn creates a `handbook_chat` chain with
child spans for retrieval and the OpenRouter call. If tracing is unavailable, the
same code uses no-op context managers and decorators.

## Design constraints

- Streamlit reruns the entrypoint on every interaction; expensive resources such
  as the retrieval engine are cached with `st.cache_resource`.
- SQLite is appropriate for a single-instance demo or small internal deployment.
  A multi-instance deployment should move persistence to a shared database.
- The embedding cache is local disk storage. Containers need a persistent volume
  for both the database and cache.
