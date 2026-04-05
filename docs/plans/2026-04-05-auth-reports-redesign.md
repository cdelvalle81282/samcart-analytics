# Auth Replacement & Report Scheduling Redesign

**Date:** 2026-04-05
**Status:** Approved

## Problem

1. `streamlit-authenticator` depends on `extra-streamlit-components` which has a broken `CookieManager` component incompatible with Streamlit 1.54+.
2. Report scheduling UI is confusing: time shown in UTC, frequency options unclear, day-of-week/day-of-month always visible.
3. Reports are delivered via Slack webhooks to channels. User wants Slack DMs to the report creator.

## Design

### 1. Custom Auth (replace streamlit-authenticator)

**Changes to `auth.py`:**
- Remove `streamlit-authenticator` import entirely.
- `require_auth()` renders a `st.form` with username/password fields when not authenticated.
- On submit, calls `auth_db.authenticate(username, password)` (already exists, does bcrypt).
- On success: sets `st.session_state["authentication_status"] = True`, `st.session_state["username"]`, loads permissions.
- On failure: shows error.
- Logout: sidebar button clears session state and reruns.
- No cookies. Session-only auth (user logs in per browser session).

**Dependencies removed:**
- `streamlit-authenticator` from requirements.txt
- `extra-streamlit-components` removed transitively
- `cookie_key` in secrets.toml no longer needed (can remain for backward compat, just ignored)

### 2. Slack Bot Integration

**secrets.toml addition:**
```toml
[slack]
bot_token = "xoxb-..."  # Bot with chat:write scope
```

**DB: `users` table gets `slack_user_id TEXT` column.**

Each user stores their Slack member ID. The User Management page and user profile allow editing this field.

**Report delivery:**
- `report_scheduler._execute_report()` resolves the creator's `slack_user_id` from the users table.
- Uses Slack `chat.postMessage` API with `channel=<slack_user_id>` to send a DM.
- Google Sheets link included in the DM message.
- `slack_webhook` and `slack_channel` columns kept in DB for backward compat but no longer required in the form.

**Slack app setup:**
1. Create app at api.slack.com/apps
2. Bot Token Scopes: `chat:write`
3. Install to workspace
4. Copy Bot User OAuth Token to `[slack] bot_token` in secrets.toml

### 3. Report Schedule Redesign

**DB schema change for `scheduled_reports`:**

Replace `frequency` with:
```sql
schedule_type    TEXT NOT NULL CHECK(schedule_type IN ('weekly','monthly'))
schedule_days    TEXT          -- comma-separated weekday indices: "0,2,4" = Mon/Wed/Fri
day_of_month     INTEGER       -- 1-28 (monthly only)
hour_utc         INTEGER NOT NULL DEFAULT 12
timezone         TEXT NOT NULL DEFAULT 'America/Los_Angeles'
```

Migration: convert existing `frequency='daily'` to `schedule_type='weekly', schedule_days='0,1,2,3,4,5,6'`.

**UI form:**
- **Schedule type:** radio — "Weekly" or "Monthly"
- **Weekly:** 7 checkboxes (Mon-Sun). Check the days you want the report.
- **Monthly:** number input 1-28.
- **Time:** time picker displayed in user's local timezone (auto-detected via JS `Intl.DateTimeFormat().resolvedOptions().timeZone`). Converted to UTC on save.
- **Removed from form:** Slack webhook URL, Slack channel (replaced by Slack DM via user profile).
- **Kept:** Report name, report type, product filter, date range, Google Spreadsheet ID.

**Display in report list:**
- "Mon, Wed, Fri at 7:00 AM Pacific"
- "Monthly on the 1st at 7:00 AM Pacific"

**Scheduler:**
- Weekly: cron fires daily at `hour_utc`, job checks if today's weekday is in `schedule_days`.
- Monthly: cron fires on `day_of_month` at `hour_utc`.

### 4. Migration Strategy

- DB migration runs in `_init_schema()` using `ALTER TABLE ... ADD COLUMN` with defaults.
- Existing reports converted: `daily` -> weekly all days, `weekly` -> weekly with single day, `monthly` -> monthly unchanged.
- Old `slack_webhook` column kept (nullable), new reports don't use it.

## Files Changed

| File | Change |
|------|--------|
| `auth.py` | Replace streamlit-authenticator with custom st.form login |
| `auth_db.py` | Add `slack_user_id` to users table, update scheduled_reports schema |
| `pages/13_User_Management.py` | Add Slack ID field to user management, redesign report schedule form |
| `report_scheduler.py` | Update trigger building for new schema, use Slack bot API for DMs |
| `notifications.py` | Add `send_slack_dm()` using bot token + chat.postMessage |
| `requirements.txt` | Remove streamlit-authenticator, keep bcrypt |
| `shared.py` | Remove streamlit-authenticator related code if any |
