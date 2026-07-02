# PrayerVault

A private, self-hosted prayer journal. Prayers and prayer requests are stored as
Obsidian-flavored Markdown notes directly in your vault, and a local Ollama model
responds to each entry with relevant Scripture (linked in `[[John 1#13|John 1:13]]`
vault format), a Reformed pastoral reflection, and suggestions for how to pray.
Track requests over time and mark them answered.

## Architecture

- **FastAPI** backend + single-page frontend, packaged in Docker
- **Storage**: your Obsidian vault (one `.md` note per prayer — no database)
- **AI**: Ollama on the host machine (`host.docker.internal:11434`)
- **Auth**: bcrypt login, signed HttpOnly session cookies, login rate limiting,
  security headers, Caddy for automatic HTTPS

## Setup

1. Copy `.env.example` to `.env`.
2. Generate a password hash: `python scripts/hash_password.py` → paste into `.env`.
3. Generate a session secret: `python -c "import secrets; print(secrets.token_hex(32))"` → paste into `.env`.
4. Set `PRAYERS_DIR` to the vault folder prayers should live in.
5. Set `OLLAMA_MODEL` to a model you have pulled (`ollama list`).
6. `docker compose up -d --build`

### Exposure options

- **Public (HTTPS)** — point a DNS record at your IP, set `DOMAIN` in `.env`,
  forward ports 80/443 to this machine. Caddy handles certificates automatically.
- **LAN-only** — comment out the `caddy` service, uncomment the `ports` mapping on
  `prayervault`, set `COOKIE_SECURE=false`, browse to `http://<pc-ip>:8800`.
- **Recommended for the long run**: put it behind Tailscale instead of the open
  internet — prayer data is sensitive, and a tailnet removes the public attack
  surface entirely while still working from your phone anywhere.

## Note format

```markdown
---
title: Healing for a friend
date: '2026-07-02'
type: request
status: ongoing        # ongoing | answered
ai: done               # pending | done | error
tags: [prayer, prayer/request]
requested-by: The Smiths
---

## Prayer
## Scripture        (AI — wikilinked verses with why they apply)
## Reflection       (AI — pastoral encouragement)
## How to Pray      (AI — adoration/confession/thanksgiving/supplication prompts)
## Updates          (timeline; answered entries recorded here)
```

## Development

```
pip install -r requirements.txt pytest
pytest tests/
```
