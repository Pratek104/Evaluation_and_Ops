# Security

## Authentication

- Users sign in with a work email and password.
- Passwords are stored as versioned PBKDF2-SHA256 hashes with a random 128-bit
  salt per account and 260,000 iterations.
- Verification uses `hmac.compare_digest` to avoid timing leaks.
- Successful and failed sign-ins and sign-outs are written to `auth_audit`.
- Inactive accounts (`is_active = 0`) cannot authenticate.

The seeded password `admin1234` is for demonstration only. Replace it before
loading real employee data. The seed routine does not overwrite existing
employee rows, so changing a hash in the database is safe.

## Authorization

Authorization is enforced at multiple layers:

1. The navigation registry only exposes pages allowed by the role.
2. Each page render function rechecks its required permission.
3. Data services apply permission-based `WHERE` clauses before returning rows.
4. Handbook retrieval removes disallowed passages before ranking.
5. The model prompt includes the user's role and scope, and the assistant is
   instructed not to speculate about data outside the supplied passages.
6. Chat history is cleared on logout and when the role or permission set changes.
7. Leave chat tools are filtered by role, and the service rechecks every
   `leave:*` permission before acting.
8. MCP tools resolve an opaque session token to an employee and then apply the
   same `leave:*` permission checks as the UI.

Roles are fixed in the seeded policy. There is no self-service role escalation
path in the UI or API. Leave self-approval is rejected even for HR; the CEO can
approve HR's request as a break-glass approver.

## Data protection

- `.env` is ignored by git. Never commit API keys or tracing credentials.
- `data/runtime/` is ignored by git, including the SQLite database and embedding
  cache.
- The database stores salary data, password hashes, and leave records; treat the
  runtime volume as sensitive.
- The assistant sends retrieved handbook text and the current question to
  OpenRouter. Do not put secrets in the handbook PDF.
- LangSmith traces may include prompts, retrieved passages, answers, and user
  identity metadata. Disable tracing or use an approved endpoint if that is not
  acceptable.

## Secrets management

For local development, `.env` is convenient. For production, inject secrets
through the platform's secret manager or environment variables and do not bake
them into container images.

Recommended rotation steps:

1. Revoke the exposed OpenRouter or LangSmith key in its dashboard.
2. Create a replacement key.
3. Update the deployment secret store.
4. Restart the application.

## Deployment hardening

- Terminate TLS at a reverse proxy or load balancer and serve the app over HTTPS.
- Do not expose Streamlit's development server directly to the public internet
  without authentication at the edge if the deployment is shared.
- Run the container as a non-root user (the provided Dockerfile does).
- Restrict network access to the runtime volume and database backups.
- Set a non-default demo password before real use.
- Treat the MCP stdio server as a local trusted-client integration. It runs as a
  subprocess under the client's OS account, and its in-memory tokens are not a
  substitute for OS isolation.
- Keep `LANGSMITH_TRACING=false` unless trace data is approved for the
  environment.
- Review dependency updates regularly.

## Known limitations

- This is a demo-grade identity system, not an SSO integration. For production,
  integrate the company identity provider (OIDC/SAML) and derive roles from
  authoritative groups.
- SQLite does not provide row-level encryption at rest. Use encrypted disks or a
  managed database for sensitive deployments.
- Streamlit session state is process-local. Horizontal scaling requires shared
  persistence and a shared session strategy.
- MCP session tokens are process-local and have no idle expiry; restarting the
  server invalidates them. Add expiry or a shared token store before exposing the
  server to multiple long-running clients.
- Free OpenRouter models share upstream rate limits and are not suitable for
  guaranteed availability.

## Reporting issues

If you discover a vulnerability, do not open a public issue with exploit details.
Report it to the repository owner or the security contact defined by your
organization.
