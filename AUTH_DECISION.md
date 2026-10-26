# Authentication decision

Updated 26 October 2026. Still is a local app with one owner, protected by a passphrase. This replaces the earlier prototype note, which recorded that the app had no authentication.

## Design

- **Where it runs:** the server binds to `127.0.0.1` only. The launcher opens it in the owner's browser. Nothing listens on the network.
- **First run:** the owner sets a passphrase of at least 12 characters.
- **Encryption:**
  - scrypt (n=2^15, r=8, p=1, random salt) derives a key from the passphrase.
  - That key wraps a random 256-bit data key with AES-GCM.
  - The data key encrypts the IBKR token, the Query ID, search keys and every imported report, each sealed with a purpose label so ciphertexts can't be swapped.
  - Duplicate reports are detected with a keyed HMAC, not a plain hash.
- **Changing the passphrase** re-wraps the data key; the data itself is not re-encrypted. There is no recovery. *Reset Still* deletes everything Still saved and starts setup again.
- **Unlocking:** a correct passphrase keeps the data key in memory until the owner chooses *Lock now* or quits. This is what lets the daily sync run unattended. Repeated failures back off exponentially, up to 5 minutes.
- **Sessions:**
  - A random 256-bit session token, held in server memory and sent as an `HttpOnly; SameSite=Strict; Path=/` cookie.
  - Idle sessions expire after the owner's chosen time (30 minutes by default). After that the passphrase is needed again, but the data key stays loaded for background syncs.
  - The cookie has no `Secure` flag because the app is served over http on loopback.
- **Request checks:**
  - Every API route except session, setup, sign-in and reset needs a valid session.
  - Requests that change anything must carry `X-Still-Request: 1`.
  - Requests are refused when they come from a foreign `Origin`, have an unexpected `Host` (DNS rebinding), or arrive cross-site via `Sec-Fetch-Site`.
  - Opening the page itself from a link elsewhere is allowed.
- **Reset without signing in:** this route exists for a forgotten passphrase. It still needs the custom header and the typed confirmation `RESET`. Any process running as the same user could delete Still's files anyway, so the route adds no new exposure.
- **Storage:**
  - SQLite in the per-user data folder: directory 0700, database 0600. On Windows, the profile's inherited permissions apply.
  - Plain settings (sync time, auto-lock, demo or IBKR mode) are not secret and are stored unencrypted.
  - Nothing sensitive is logged; the server logs no requests at all.

## What this does not cover

- **Other software running as the same user.** It can read Still's memory while the app is unlocked, or install a keylogger. Use the operating system's account security.
- **Remote or multi-user access.** It is deliberately out of scope. Exposing the server through a tunnel or reverse proxy would skip TLS and the host checks; don't do it.
- **A hosted service.** It would need real identity (for example WorkOS AuthKit, or the hosting platform's sign-in), TLS, server-side secret management, per-user data separation and IBKR's agreement for collecting customer tokens. See [docs/IBKR_SETUP.md](docs/IBKR_SETUP.md#staying-within-ibkrs-flex-rules).

The earlier static preview at https://still-investing-workspace.anshulraj.chatgpt.site has no server, so it shows demo data only and offers no credential forms.

## Tests

`tests/test_app.py` checks the following:
- vault round trips, a wrong passphrase, tampering and passphrase change
- file permissions, and no plaintext secrets on disk
- session expiry, lock and backoff
- every private route returns 401 without a session
- the header, Origin, Host and cross-site checks
- reset
