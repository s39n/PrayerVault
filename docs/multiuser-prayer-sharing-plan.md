# PrayerVault → Shared Prayer App: Architecture Plan

**Status:** Proposal · **Date:** 2026-07-13 · **Author:** Sean (+ Claude)

Turn PrayerVault from a single-user Markdown journal into a **multi-church** app where
people can **request prayer from specific people, from their church's elders, or a
group** ("Elders, John needs prayer for his upcoming job interview") — where one person
**owns** each shared prayer, **others can add updates**, and **followers get notified**.
Multiple churches share one deployment with **strict data isolation** between them.

---

## 1. Where we are today

The current app is already further along than the CLAUDE.md suggests. What exists:

- **Auth:** admin (bcrypt password) + open **Google sign-in** (`google_auth.py`).
  Sessions are signed cookies (`itsdangerous`), `SameSite=Strict`, HttpOnly.
- **Per-user storage, but siloed:** each Google user gets their own private folder
  of Markdown notes (`users.py::vault_for`). The admin keeps the Obsidian vault.
  **Users cannot see each other's prayers at all** — there is no sharing primitive.
- **Prayers = Markdown files** with YAML frontmatter + `## Section` bodies
  (`notes.py`). Ownership is implicit (whoever's folder it's in). "Requested-by" is
  just a free-text string, not a real user link.
- **Updates** exist, but only the folder owner can add them (`add_update`).
- **Notifications:** one daily "morning verse" push via **ntfy** only
  (`notify.py`, `_morning_loop`). No per-event, per-user, or multi-channel delivery.
- **Constraints to respect:** CSP is `script-src 'self'` (no inline JS, no CDN),
  frontend is dependency-free vanilla JS, AI content stays Reformed voice, personal
  notes are user data synced to Obsidian and must not be bulk-rewritten.

**The gap:** everything today is single-owner and private. Groups, shared ownership,
cross-user updates, subscriptions, and event notifications are all new.

---

## 2. The core decision: a database alongside the vault

You chose to add a database. The cleanest split:

**The database is the source of truth for everything *relational and multi-user*** —
users, groups, memberships, ownership, who-follows-what, notification preferences,
and the delivery log. **Markdown stays the format for prayer *content*** so your
existing AI enrichment, embeddings/search, and Obsidian sync keep working unchanged.

Concretely:

- **Private journal prayers** (type `prayer`, `prayer/personal`) → keep exactly as
  today: a Markdown file in the user's folder. No DB row needed unless shared.
- **Shared prayers** (requested from people, or posted to a group) → a **DB row is
  the record of truth** (owner, group, status, permissions, subscribers). The prayer
  *body + AI sections* are stored as a Markdown blob **in a DB column** — **not**
  mirrored to your Obsidian vault (decided: shared prayers live only in the app/DB).
  Storing the body as Markdown still lets `ollama_client._shape()` and `embeddings`
  operate on the same `## Section` text with almost no change.

**Engine:** **SQLite** to start (single-file, zero-ops, already your deployment
style, fine for a congregation-sized user base), accessed via **SQLModel**
(SQLAlchemy + Pydantic — plays nicely with FastAPI). A later move to Postgres is a
connection-string change, not a rewrite. Use **Alembic** for schema migrations from
day one so the DB can evolve without hand-editing.

> Why not "Markdown only"? Encoding group membership, per-user follow state, and a
> notification queue in YAML frontmatter means every permission check is a full
> vault scan and every notification is a race condition. A 12-line schema removes
> that whole class of problems.

---

## 3. Roles & permissions

Roles live at **three tiers**: the platform (you, running the service), the **church**
(each tenant), and the **group**. **`elder` is a fixed church-wide role**, distinct
from being a group leader.

**Platform tier** (across all churches)

| Role         | Who         | Powers                                                    |
|--------------|-------------|-----------------------------------------------------------|
| `superadmin` | You (Sean)  | Create/suspend churches, platform settings, billing later |

**Church tier** (a user's role *within their church*, on the membership row)

| Role     | Who                     | Powers                                                                 |
|----------|-------------------------|------------------------------------------------------------------------|
| `admin`  | Pastor / church admin   | Manage this church's users, groups, elders, settings; invite anyone    |
| `elder`  | **Fixed church role**   | Receive prayer requests sent "to the elders"; own/shepherd shared prayers; church-wide pastoral visibility |
| `member` | Congregant              | Create prayers, request prayer, join groups, follow, add updates       |

Elders are a **standing set within a church**, not tied to any one group. There's a
built-in **"Elders" destination** every member can send a request to — that's your
example: a member posts "John needs prayer for his interview" **to the elders**, an
**elder becomes the owner** and shepherds it, any subscriber adds updates.

**Group tier** (per-group membership role)

| Group role | Powers                                                                        |
|------------|-------------------------------------------------------------------------------|
| `leader`   | Manage a group, own/assign its prayers, moderate, **send invites into the group** |
| `member`   | Post prayer needs to the group, add updates, follow prayers                   |

A group leader may or may not be an elder — the two roles are independent. **Group
leaders can send invitations** (decided), so a leader can bring someone straight into
their group without waiting on a church admin.

---

## 3b. The Elder View — the pastoral dashboard

The member side is simple: write a prayer, optionally **send it to the elders** or a
group. But the **elder experience is the heart of the app** — elders shepherd people,
so they get a dedicated view built around *care and follow-through*, not just a list.

**Layout — an elder's home screen**

1. **Incoming queue** — every request sent "to the elders" that **no one has claimed
   yet.** One tap to **"I've got this"** (claim ownership) or **assign to another
   elder**. Nothing falls through the cracks because unclaimed items sit at the top.
2. **My flock** — prayers I own/shepherd, grouped by status (ongoing / answered), each
   showing who requested it, the subject, and last activity.
3. **Needs follow-up** — ongoing prayers I own with **no update in N days** (default
   7). This is the gentle nudge that turns "I'll pray for you" into ongoing care.
4. **Recently answered** — a testimony feed of God's faithfulness across the church,
   good for encouragement and for sharing in a service.

**Elder-only capabilities**

- **Pastoral notes** — an elder-only note field on a prayer (visible to elders/owner,
  **never** to the member). For "called Tuesday, following up after his interview."
  Clearly labelled as private so it's never confused with a member-visible update.
- **Claim / hand off** — take ownership, or pass a prayer to the elder best suited to
  walk with that person.
- **Add a member-visible update** or **mark answered** with a word of encouragement
  (can reuse the AI Scripture/Reflection to offer a verse + pastoral note).
- **Church-wide pastoral visibility** of *shared* prayers (elders/groups) — **not**
  members' private journals. Care, not surveillance.

This keeps the member flow dead simple while giving elders a real tool for the work.

---

## 3c. Onboarding & guided walkthroughs

New users shouldn't land on a blank screen. Three short, **role-aware** first-run
walkthroughs, plus a dismissable checklist:

- **Church admin (first person in a new church):** name the church → invite elders →
  create a first group. A setup checklist card tracks what's left.
- **New member:** "Here's how to write a prayer, how to send one to the elders or a
  group, and how you'll be notified." 3–4 friendly steps, skippable.
- **New elder:** a tour of the Elder View (§3b) — the queue, claiming, follow-ups,
  pastoral notes — so they understand the shepherding tools on day one.

**How it's built (respecting the constraints):** a lightweight, **in-house** step
walkthrough — small coach-mark/overlay panels driven by vanilla JS, no third-party
tour library (keeps `script-src 'self'` and the dependency-free frontend intact).
State ("has seen member tour") lives on the user row so it shows once and can be
re-triggered from a Help menu.

**Ownership rules**

- The **creator owns** a prayer by default.
- A request sent **to the elders** is owned by whichever **elder claims/is assigned**
  it (your "that elder owns the prayer"). A prayer posted to a group can be assigned
  to a **group leader**.
- **Only the owner** (or the relevant leader/elder, or church admin) can change status
  (answered/reopen), edit the request text, or delete.
- **Any subscriber** can **add updates** (append-only) — updates are never
  destructive, matching today's timeline model.

**Permission matrix** (all scoped to the same church)

| Action                        | Owner | Elder / Grp leader | Church admin | Member/Follower | Other church |
|-------------------------------|:-----:|:------------------:|:------------:|:---------------:|:------------:|
| View prayer                   | ✅    | ✅*                | ✅*          | if shared       | ❌ never     |
| Add update                    | ✅    | ✅                 | ✅           | if subscribed   | ❌           |
| Mark answered / reopen        | ✅    | ✅                 | ✅           | ❌              | ❌           |
| Edit request text             | ✅    | ✅                 | ✅           | ❌              | ❌           |
| Assign / transfer ownership   | ✅    | ✅                 | ✅           | ❌              | ❌           |
| Delete / hide                 | ✅    | ✅                 | ✅           | ❌              | ❌           |
| Send invitations              | —     | ✅ (grp leader)    | ✅           | ❌              | ❌           |

*Elders/admins see prayers **addressed to elders or their groups** — not every
member's private journal. A prayer in **another church is never visible**, full stop.

---

## 4. Visibility / sharing modes

Every prayer has a **visibility** that determines who can see it:

1. **`private`** — only the owner. This is today's journal. Default for `type: prayer`.
2. **`direct`** — a request shared with **named individuals** ("request prayer from
   certain people"). Those people can view, follow, and add updates.
3. **`elders`** — a request sent to the **church's elders** (the built-in destination).
   All elders in that church can see it; one becomes the owner.
4. **`group`** — posted to a **group**; all current group members can view/follow,
   the owner (or an assigned leader) shepherds it.

Every visibility mode is **scoped to the requester's church** — sharing never crosses
church boundaries.

A prayer can start `private` and be **promoted** to `direct`/`group` later (share
button), but never silently — sharing is an explicit action, and you can **unshare**
back to private.

---

## 5. Data model

`snake_case`, SQLite/SQLModel. **Every church-owned table carries `org_id`** — that
column is the tenant boundary, filtered on every query (see §5b).

```
organizations                    -- a church (the tenant)
  id (uuid pk) · name · slug (unique, e.g. "grace-pca")
  status (pending_verify|active|suspended) · created_by (fk users) · created_at
  settings_json (branding, elder-request on/off, allowed email domain,
                 follow_up_days [default 7])

users
  id (uuid pk) · org_id (fk organizations) · email · display_name
  auth_provider (google|password) · google_sub (nullable, unique)
  password_hash (nullable) · onboarded_json (which tours seen) · created_at
  -- one person = one church; a second church means a second email/account (decided)

memberships                      -- a user's church-tier role
  id · org_id (fk) · user_id (fk)
  role (admin|elder|member) · status (active|invited) · created_at
  UNIQUE(org_id, user_id)

groups
  id (uuid pk) · org_id (fk) · name · slug · description
  created_by (fk users) · created_at

group_members
  id · org_id (fk) · group_id (fk) · user_id (fk)
  role (leader|member) · status (active|invited|requested) · joined_at
  UNIQUE(group_id, user_id)

prayers                          -- the source-of-truth row for a shared prayer
  id (uuid pk) · org_id (fk) · title · kind (prayer|request)
  owner_id (fk users, nullable until an elder claims) · subject_name
  visibility (private|direct|elders|group) · group_id (fk, nullable)
  status (ongoing|answered) · answered_at (nullable)
  body_md (the "## Prayer" text + AI sections) · ai_status (pending|done|error)
  created_at · updated_at

prayer_shares                    -- for visibility=direct: named recipients
  id · org_id (fk) · prayer_id (fk) · user_id (fk) · created_at
  UNIQUE(prayer_id, user_id)

prayer_updates                   -- append-only timeline (replaces "## Updates")
  id · org_id (fk) · prayer_id (fk) · author_id (fk users)
  text · kind (update|answered|reopened|created) · created_at

pastoral_notes                   -- ELDER-ONLY notes; never shown to the member (§3b)
  id · org_id (fk) · prayer_id (fk) · author_id (fk users, an elder)
  text · created_at
  -- enforced elder-only at the data layer; excluded from all member-facing responses

subscriptions                    -- who follows a prayer -> who gets notified
  id · org_id (fk) · prayer_id (fk) · user_id (fk)
  muted (bool) · created_at
  UNIQUE(prayer_id, user_id)

notification_prefs               -- per user, per channel toggles
  user_id (pk fk) · email_enabled · webpush_enabled · sms_enabled
  ntfy_enabled · ntfy_topic · digest_weekly (bool) · digest_day (0-6)
  email_address · phone_e164 · webpush_subscription_json (nullable)

notifications                    -- outbox / delivery log (idempotent, auditable)
  id · org_id (fk) · user_id (fk) · prayer_id (fk, nullable) · event_type
  channel (email|webpush|sms|ntfy|digest) · payload_json
  status (queued|sent|failed) · error · created_at · sent_at

invitations                      -- invite links to a church and/or group
  id · org_id (fk) · email · group_id (fk, nullable)
  church_role (member|elder|admin) · group_role (leader|member, nullable)
  token (signed) · invited_by (fk) · accepted_at (nullable) · expires_at
```

### 5b. Tenant isolation (the part that must never leak)

With multiple churches sharing one database, the **cardinal rule is that a query for
church A can never return church B's rows.** How to guarantee it:

- **`org_id` on every church-owned table**, indexed, and part of the composite
  uniqueness constraints.
- **Resolve `org_id` from the session, never from client input.** The signed session
  cookie carries `user_id`; the server looks up that user's `org_id` and injects it
  into every query. A request can't ask for another church's data because it never
  supplies the `org_id`.
- **One choke point.** Route all reads through a small data layer that *requires* an
  `org_id` argument (or a SQLAlchemy global filter / session-scoped default), so no
  hand-written query can forget the filter. This is the single most important
  correctness property of the whole system — worth a dedicated test suite.
- **Cross-church references are impossible by construction:** a group, prayer, or
  invite can only reference users in the same `org_id`.

Notes:
- **AI sections** (Scripture / Reflection / How to Pray / Related) for a shared
  prayer can live in `body_md` as today's `## Section` blocks, or split into columns.
  Keeping them in one `body_md` blob means `ollama_client._shape()` and
  `embeddings` need almost no change — they operate on the same section text.
- `subscriptions` is the notification fan-out: group members are auto-subscribed on
  post; direct recipients auto-subscribed on share; anyone can follow/mute.

---

## 6. Notifications: multi-channel dispatcher

A single **event → subscribers → per-user channels** pipeline. When something
happens, enqueue one `notifications` row per (subscriber × enabled channel), then a
background worker delivers and marks sent/failed. Idempotent, retryable, auditable.

**Events that notify**

| Event              | Fires when…                          | Who's notified                    |
|--------------------|--------------------------------------|-----------------------------------|
| `prayer.created`   | request shared to group/individuals  | group members / named recipients  |
| `prayer.update`    | someone adds an update               | all subscribers (except author)   |
| `prayer.answered`  | owner marks answered                 | all subscribers                   |
| `prayer.assigned`  | ownership assigned to an elder       | the new owner                     |
| `group.invited`    | invited/added to a group             | the invitee                       |

**Channels** (all pluggable behind one `Notifier` interface; each is independent so
you can ship one at a time):

- **NTFY** — keep it. Already wired (`notify.send_ntfy`); becomes one channel among
  several, driven per-user by `notification_prefs.ntfy_topic`.
- **Email** — SMTP (e.g. your own server, or a provider like Resend/Postmark/SES).
  Best default: works with no app install, needed anyway for invitations. Env:
  `SMTP_HOST/PORT/USER/PASS`, `MAIL_FROM`.
- **Web push** — browser push via **VAPID**. You already ship a service worker
  (`sw.js`) and manifest, so the PWA plumbing exists; add a push subscription
  handshake + `pywebpush`. CSP already allows `script-src 'self'` (no change needed).
- **SMS** — Twilio (or similar). Highest engagement, but costs money and needs phone
  numbers — gate behind a per-user opt-in with a verified `phone_e164`.
- **Weekly digest** — a scheduled job (extend the existing `_morning_loop` pattern,
  or move to a proper scheduler) that batches each user's group needs + updates into
  one message on their chosen day/channel, for people who don't want per-event pings.

**Per-user control:** `notification_prefs` lets each person pick channels and choose
"every event" vs "weekly digest" vs "muted". Per-prayer `subscriptions.muted` lets
them silence a single noisy thread.

---

## 7. API surface (new/changed routes)

Building on the existing FastAPI app:

```
# Church self-serve signup (public) — §11
POST   /api/churches                    create a church; founder becomes admin (pending verify)
GET    /api/churches/verify             confirm founder email -> church goes active
GET    /api/churches/settings           church settings incl. follow_up_days (admin)
POST   /api/churches/settings           update branding / follow_up_days / toggles (admin)

# Groups
POST   /api/groups                      create group (creator becomes leader)
GET    /api/groups                      groups I'm in
GET    /api/groups/{id}                 group detail + members + prayers
POST   /api/groups/{id}/members         invite / add member (leader)
POST   /api/groups/{id}/join            request to join
DELETE /api/groups/{id}/members/{uid}   remove member (leader)

# Prayers (extend existing /api/prayers)
POST   /api/prayers                     + visibility, group_id, share_with[], subject_name
POST   /api/prayers/{id}/share          promote private -> direct/group
POST   /api/prayers/{id}/assign         assign/transfer ownership (owner/leader)
POST   /api/prayers/{id}/subscribe      follow / unfollow / mute
POST   /api/prayers/{id}/updates        (exists) now authored by any subscriber
GET    /api/feed                        prayers shared with me across groups

# People
GET    /api/people                      searchable directory (for "request from…")
GET    /api/directory/groups            groups I can request to

# Elder view (elder role required; all org-scoped) — §3b
GET    /api/elders/queue                unclaimed requests sent to the elders
POST   /api/prayers/{id}/claim          elder claims ownership ("I've got this")
GET    /api/elders/my-flock             prayers I own/shepherd, by status
GET    /api/elders/follow-up            my ongoing prayers with no update in N days
GET/POST /api/prayers/{id}/pastoral-notes   elder-only notes (never member-visible)

# Onboarding — §3c
GET    /api/onboarding                  which role-aware tours to show me
POST   /api/onboarding/seen             mark a tour completed/skipped

# Notifications
GET    /api/notifications               my in-app notifications
POST   /api/notifications/read          mark read
GET/POST /api/notification-prefs        channel toggles, phone, digest day
POST   /api/push/subscribe              store web-push subscription
POST   /api/invitations/accept          accept an emailed invite

# Admin (extend require_admin)
GET/POST /api/admin/users, /api/admin/groups
```

Every prayer route gains a **permission check** (Section 3 matrix) instead of
today's implicit "it's in your folder."

---

## 8. Security & privacy considerations

- **Sharing is opt-in and reversible.** Prayers are private by default; nothing
  becomes visible to others without an explicit share. Add an "unshare / make
  private" path and a clear indicator of who can see a prayer.
- **Sensitive content.** Prayer requests are deeply personal (health, relationships,
  sin). Treat every shared prayer as sensitive: no public/unauthenticated views,
  audit ownership transfers, and consider letting owners **redact the subject's name**
  when sharing broadly.
- **Auth hardening for real multi-user (decided: gate signup).** Today Google signup
  is fully open. New signups will be **gated behind invitations** (Section 5): a
  person can only create an account by accepting an emailed invite (from you as admin,
  or from a group leader inviting them into a group). Google sign-in stays the login
  method — the *first* sign-in just requires a valid, unexpired invitation token; the
  `invitations` table is the allow-list. Optionally also allow-list a church email
  domain as a convenience. This means **email is a hard dependency** (invites need to
  be sent), so build the email channel early.
- **Permission checks server-side, always** — never trust the client's visibility.
- **CSP stays intact.** Web push works within `script-src 'self'`; keep no-inline-JS.
- **Rate limits.** Extend the existing per-user AI limit to cover notification sends
  (prevent an update-spam storm) and invitations.
- **Data ownership.** Keep the "export my prayers" path; add "delete my account →
  purge or reassign my owned group prayers" for GDPR-style hygiene.
- **Tenant isolation is the #1 security property** (§5b). One church seeing another's
  prayer requests would be a catastrophic breach of trust. Enforce `org_id` filtering
  at a single data-layer choke point and cover it with dedicated tests. Each church
  also gets its own invitation allow-list and (optionally) email domain.
- **Self-serve church creation needs an anti-abuse guardrail.** Because anyone can
  create a church, require the **founding admin to verify their email** before the
  church goes `active` (hence the `pending_verify` state), rate-limit creation per
  IP/email, and give the superadmin a way to suspend a church. Only *members* still
  join by invitation — that gate is unchanged.

---

## 9. Migration path (no data loss)

1. **Additive, not destructive.** Introduce the DB *next to* the vault. Existing
   Markdown journals keep working untouched — they're all `visibility=private` and
   don't need DB rows until shared.
2. **Backfill users.** Create a `users` row per existing Google profile
   (`users.py` already stores `profile.json`) + the admin. One-time script.
3. **Lazy prayer rows.** A private prayer only gets a `prayers` row the first time
   it's shared. No mass import of the Obsidian vault (respects "never bulk-rewrite
   note files").
4. **Ship behind a flag.** `FEATURES_SHARING=false` by default; you dogfood groups
   before opening them up.

---

## 10. Phased build plan

**Phase 0 — Foundations (no user-visible change)**
DB + SQLModel + Alembic; `organizations` + `org_id` on every table; the **tenant-scoped
data layer + isolation tests** (§5b) — this is the load-bearing piece; `users`/
`memberships`/`invitations` tables; backfill your vault into a first "church" of one;
`Notifier` interface with NTFY as channel one, **plus the email channel** (needed for
invites). Tests stay offline.

**Phase 1 — Churches, gated signup, elders & groups**
Self-serve church creation with founder email verification; invite-only member signup
on Google login; church settings (incl. `follow_up_days`); church-tier roles
(admin/elder/member); the built-in **"request prayer from the elders"** flow; the
**Elder View** (§3b — queue, claim, my flock, follow-up, pastoral notes); create/join
groups; group leaders invite; permission matrix; updates by any subscriber; ownership
claim/assign. *This delivers your core example, elder-first and multi-tenant.*

**Phase 2 — Direct requests**
"Request prayer from these people," people directory, per-recipient shares + follow.

**Phase 3 — Notifications**
Event pipeline + outbox worker (reusing the email channel from Phase 0). Add web push
+ in-app bell. SMS and weekly digest as opt-in add-ons.

**Phase 4 — Polish**
Notification preferences UI, mute/unsubscribe, admin console, account deletion/export,
and the **role-aware onboarding walkthroughs** (§3c) for admin, member, and elder.

Each phase is independently shippable and testable, commits along the way per your
GitHub-first workflow.

---

## 11. Decisions & remaining questions

**Decided**

- ✅ **Signup is gated** behind invitations (§8). Google login stays; first sign-in
  requires a valid invite token tied to a specific church. Email channel is built in
  Phase 0 since invites depend on it.
- ✅ **No Obsidian sync for shared prayers.** Shared prayers live only in the app DB.
  Private journal prayers still sync to the vault; only shared ones stay app-only.
- ✅ **`elder` is a fixed church-wide role** (§3), with a built-in "to the elders"
  request destination — not a per-group role.
- ✅ **Group leaders can send invitations** into their own group (§3).
- ✅ **Multi-tenant from the start.** The app hosts multiple churches; `org_id` scopes
  every church-owned table and is enforced at one data-layer choke point (§5b). You
  are the platform `superadmin`; each church has its own admin, elders, and members.
- ✅ **One person = one church.** Belonging to a second church means a second account
  under a different email. Keeps tenancy dead simple (no per-request church switcher).
- ✅ **Dedicated Elder View** (§3b) — a pastoral dashboard (queue, claim, my flock,
  follow-up nudges, elder-only pastoral notes). Members simply see "send to the
  elders"; elders get the real shepherding tools. Ships in Phase 1.
- ✅ **Role-aware onboarding walkthroughs** (§3c) for church admin, member, and elder —
  built in-house (vanilla JS, no tour library) to keep the CSP/dependency rules.

- ✅ **Churches self-serve.** Anyone can create a church and become its admin; the
  founding admin **verifies their email** (church starts `pending_verify` → `active`)
  as the anti-abuse gate (§8). Members still join by invitation only.
- ✅ **Follow-up window is configurable per church** — `follow_up_days` in the church
  settings (default 7) drives the elder "Needs follow-up" list (§3b).

**Still open**

1. **Congregation / tenant scale:** rough number of churches and members each?
   (SQLite is fine into the low thousands total; heavy multi-tenant load would later
   argue for Postgres + a per-church schema or row-level security.)
2. **Branding per church:** do churches need their own name/logo/colors, or is a
   shared look fine for now? (Schema already reserves room in `settings_json`.)
```
