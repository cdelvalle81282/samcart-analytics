# PII Approval Token Hardening

**Status:** Not yet implemented  
**Priority:** Medium — implement if external users can request PII access, or if compliance requires it. Internal-only usage is lower risk.

---

## Background

When a user requests PII access, an approval email is sent to an admin containing a GET link:

```
https://opisamcart.duckdns.org/PII_Approval?token=abc123&request_id=42
```

The token is a deterministic HMAC of the `request_id`. Three security issues were identified.

---

## Issue 1 — Tokens never expire (easiest, highest value)

**Problem:** A pending request can sit for months. A leaked or forwarded approval link still works indefinitely.

**Fix:**
- In `pii_access.py`: when creating a request, store `expires_at = datetime('now', '+24 hours')` in the DB.
- In the approval handler: check `expires_at` before processing. If expired, return an error page instead of approving.
- Migration: `ALTER TABLE pii_access_requests ADD COLUMN expires_at TEXT`.

**Tradeoff:** Admins must approve within 24 hours or the requester must re-submit. Adjust window if needed.

---

## Issue 2 — Token travels in GET URL

**Problem:** Tokens in GET URLs are logged by nginx, stored in browser history, and may be scanned by email providers that rewrite links.

**Fix:**
- Change the approval email link to open a page that shows "Approve" / "Deny" buttons.
- Those buttons POST the token in the request body (hidden form field or HTMX).
- The token is never in the URL — it only travels in the POST body over TLS.

**Files to change:** `email_sender.py` (email template), `pages/11_PII_Approval.py` (approval handler).

---

## Issue 3 — Tokens are reusable (one-shot)

**Problem:** The same approval link can be clicked multiple times. The UPDATE statement uses `WHERE status = 'pending'` which prevents re-approval, but the token itself is never invalidated.

**Fix:**
- Add a `token_used BOOLEAN DEFAULT 0` column to the requests table.
- On first approval or denial, set `token_used = 1`.
- On any subsequent use of the same token, reject with "This link has already been used."

**Migration:** `ALTER TABLE pii_access_requests ADD COLUMN token_used INTEGER DEFAULT 0`.

---

## Recommended implementation order

1. **Issue 1** (expiry) — standalone, no UI changes, low risk.
2. **Issue 3** (one-shot) — one column + one UPDATE, also standalone.
3. **Issue 2** (POST-based) — requires changing the email template and the approval page UI.

Issues 1 and 3 can be shipped together in ~30 minutes. Issue 2 is a separate UI change.

---

## Files involved

| File | Change |
|------|--------|
| `auth_db.py` | Schema migration for `expires_at`, `token_used` |
| `pii_access.py` | Set `expires_at` on create; check expiry + `token_used` on approval |
| `email_sender.py` | Update email template (Issue 2 only) |
| `pages/11_PII_Approval.py` | Switch from GET-based approval to POST buttons (Issue 2 only) |
