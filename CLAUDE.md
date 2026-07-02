# PrayerVault

Self-hosted prayer journal for Sean. Prayers/requests are stored as Obsidian-flavored
Markdown notes directly in his vault; a local Ollama model adds Scripture, a Reformed
(Presbyterian, Westminster Standards) pastoral reflection, and prayer prompts to each note.

## Architecture

- `app/main.py` — FastAPI routes, security-header middleware, background AI tasks
- `app/auth.py` — bcrypt login, signed session cookies (itsdangerous), per-IP login rate limiting
- `app/notes.py` — the storage layer. No database: one `.md` file per prayer in `VAULT_DIR`.
  Parses/renders YAML frontmatter + `## Section` bodies
- `app/ollama_client.py` — Ollama `/api/chat` (JSON mode) + `_shape()` which converts the
  model's raw JSON into note sections and builds verse wikilinks
- `app/static/` — single-page frontend (`index.html` + `app.js`), no framework, no build step
- `Dockerfile`, `docker-compose.yml`, `Caddyfile` — app container + Caddy for public HTTPS

## Note format (do not break this)

```markdown
---
title: Healing for a friend
date: '2026-07-02'
type: request            # prayer | request
status: ongoing          # ongoing | answered (+ answered-date when answered)
ai: done                 # pending | done | error
tags: [prayer, prayer/request]   # prayer/personal for type: prayer
requested-by: The Smiths # only on requests
---

## Prayer
## Scripture       (AI) wikilinked verses + one-line "why"
## Reflection      (AI) pastoral encouragement
## How to Pray     (AI) ACTS-style bullet prompts
## Updates         timeline: "- YYYY-MM-DD — text"; answered entries land here
```

- Section order is enforced by `notes.SECTION_ORDER`
- Verse links MUST use Sean's vault format: `[[John 1#13|John 1:13]]`, ranges link the
  first verse only: `[[John 1#13|John 1:13-16]]` (built by `ollama_client._wikilink`)
- The `prayer` tag is how `list_notes()` recognizes app-owned notes; `_safe_path()`
  guards against path traversal — keep both intact
- Note IDs are filename stems (`YYYY-MM-DD Title Slug`); they appear in URLs

## Commands

```powershell
# Tests (run before every commit)
pip install -r requirements.txt pytest
pytest tests/

# Run locally without Docker
$env:SESSION_SECRET="dev"; $env:AUTH_PASSWORD_HASH="<hash>"; $env:VAULT_DIR="C:\tmp\vault"; $env:COOKIE_SECURE="false"
uvicorn app.main:app --reload

# Deploy
docker compose up -d --build
```

## Configuration

All config is env vars read in `app/config.py` (see `.env.example`): `AUTH_USERNAME`,
`AUTH_PASSWORD_HASH` (generate via `scripts/hash_password.py`), `SESSION_SECRET`,
`OLLAMA_URL`/`OLLAMA_MODEL`/`OLLAMA_TIMEOUT`, `VAULT_DIR`, `COOKIE_SECURE`, and for
compose: `PRAYERS_DIR` (host vault path) and `DOMAIN` (Caddy). App fails fast at startup
if secrets are missing. Never commit `.env`.

## Constraints & conventions

- Production vault path: `C:\Users\Sean\Documents\SecondBrain\Atlas\Faith & Ministry\Prayers\Prayer Journal`
  — the vault is its own git repo (s39n/SecondBrain) and syncs to Sean's devices; treat
  note files as user data, never bulk-rewrite them
- Single user by design; auth is bcrypt + SameSite=Strict HttpOnly cookie. Don't weaken
  headers/CSP in `main.py` (`script-src 'self'` means no inline JS in index.html — JS
  lives in `app.js`)
- Frontend must stay dependency-free (no CDN, no build step)
- AI content: Reformed/Presbyterian voice, real Scripture references only; the model
  returns JSON per `SYSTEM_PROMPT` and `_shape()` tolerates malformed entries by dropping them
- Tests mock `ollama_client.generate`; keep them passing offline
- Git: commit after meaningful progress, push to GitHub (private repo s39n/PrayerVault);
  conventional commit prefixes (feat/fix/refactor/docs/test/chore)
