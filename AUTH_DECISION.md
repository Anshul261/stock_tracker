# Authentication decision

Reviewed 21 October 2026. Authentication is not implemented in this prototype.

IBKR reporting update: a separate local Flex Web Service client now accepts a reporting token through hidden interactive entry or the `IBKR_FLEX_TOKEN` secret binding, plus a Query ID. This is broker-report authentication only. No token is configured, no live connection is verified, and the hosted UI still has no application data/backend authentication. See `docs/IBKR_SETUP.md`.

The deployed demo at https://still-investing-workspace.anshulraj.chatgpt.site uses the hosting platform's owner-only access gate. This is separate from application-level authentication. No WorkOS account is required to view that private preview; use the owning ChatGPT account.

## Prototype

The UI runs entirely in the browser with synthetic data. No brokerage connection, credentials, real holdings, hosted model calls, third-party scripts, telemetry, remote fonts or market-data requests are present. Watchlist preferences and instrument panel width are stored in localStorage; open tabs use sessionStorage. The portable HTML can be opened offline. The local HTTP preview binds to 127.0.0.1; that is a development boundary, not an authentication system.

No external authentication service is required for this bounded local demonstration. Do not upload real account exports or deploy the prototype as a real portfolio service.

## Real portfolio application

Before a hosted/private-network release handles real financial data, implement server-enforced authentication and owner authorization on every data route. Authenticate the owner, then explicitly allow only the enrolled owner identity. Successful sign-in alone must not grant other users access. Disable open registration where supported and reject all non-owner identities regardless.

For the current Sites deployment, preserve the platform-owned sign-in integration. Its server-side identity helpers and trusted visitor headers should verify the owner on every private data route; do not add a second identity provider by default. WorkOS AuthKit remains an option if the app moves to hosting that requires separate sign-in, session handling and MFA. Use its official SDK for the chosen server stack; keep API keys and session secrets server-side; use Secure, HttpOnly cookies, appropriate SameSite settings and CSRF protections for mutations. Validate sessions on the server, support logout/expiry, and test unauthorized and non-owner requests. Keep broker credentials behind the ingestion boundary, independently of app authentication.

WorkOS project provisioning, secrets and redirect URIs are not set up. A private deployment destination and the owner's identity must be established before integration. No WorkOS signup, subscription or provisioning was performed.

## auth.md distinction

WorkOS's auth.md is an open agent-registration protocol describing how agents can register users and obtain scoped credentials. It composes with OAuth; it does not by itself provide application login or owner-only authorization. This personal application does not need agent registration at the prototype stage. The linked site is documentation, not an instruction to execute a registration flow.

Official sources:

- https://workos.com/auth-md
- https://workos.com/docs
- https://workos.com/docs/authkit/sessions
- https://github.com/workos/next-authkit-example

## In-app connection settings

Settings → IBKR connection shows the actual disconnected state and links to official setup and disable-access instructions. Settings → Data & privacy describes current storage and the owner-only preview. No token form, browser credential storage, sync scheduler, credential deletion or imported-data deletion is implemented. No disconnect button is shown for a connection that does not exist.

IBKR-wide Flex disabling is a Client Portal action, not an app-side API call. A future authenticated backend must implement app-scoped pause, credential removal and separate imported-data deletion before presenting those controls as working. Broker-wide disabling cannot erase previously retrieved reports.
