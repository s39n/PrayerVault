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
- **PWA**: installable on mobile and desktop (manifest + service worker); the app
  shell is cached for offline startup, prayer data always loads live

## Setup

1. Copy `.env.example` to `.env`.
2. Generate a password hash: `python scripts/hash_password.py` → paste into `.env`.
3. Generate a session secret: `python -c "import secrets; print(secrets.token_hex(32))"` → paste into `.env`.
4. Set `PRAYERS_DIR` to the vault folder prayers should live in.
5. Set `OLLAMA_MODEL` to a model you have pulled (`ollama list`).
6. `docker compose up -d --build`

### Install as an app

PrayerVault is a PWA. On desktop Chrome/Edge, use the install icon in the address
bar. On Android, Chrome menu → *Add to Home screen* → *Install*. On iOS, Safari
share sheet → *Add to Home Screen*. (Requires HTTPS unless on `localhost`.)

### Exposure options

- **Public (HTTPS)** — point a DNS record at your IP, set `DOMAIN` in `.env`,
  forward ports 80/443 to this machine. Caddy handles certificates automatically.
- **LAN-only** — comment out the `caddy` service, uncomment the `ports` mapping on
  `prayervault`, set `COOKIE_SECURE=false`, browse to `http://<pc-ip>:8800`.
- **Recommended for the long run**: put it behind Tailscale instead of the open
  internet — prayer data is sensitive, and a tailnet removes the public attack
  surface entirely while still working from your phone anywhere.

## Sharing with others (Google sign-in)

PrayerVault stays single-admin: your prayers live in your Obsidian vault and
password login keeps working. Optionally, you can let others use the app with
their Google account — each Google user gets their own private folder under
`USERS_DIR` (never your vault), the same AI features (rate-limited to 30
AI calls/hour per user), and backup tools. Everyone (you included) gets a
**Download .zip** button, plus **Back up to Google Drive** which uploads a zip
to the user's own Drive using the `drive.file` scope (the app can only see
files it created).

To enable it, create an OAuth client in Google Cloud Console (steps in
`.env.example`), set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, make sure
`PUBLIC_URL` (or `DOMAIN`) matches your registered redirect URI, and restart.
Leave the variables unset and every Google feature stays hidden.

Admin-only areas: the You tab's morning prompt and AI prompt settings. Google
users see an account card and backups there instead.

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

## Deploying on a NAS

Every push to `master` runs the tests and publishes a private multi-arch image
(amd64 + arm64) to `ghcr.io/s39n/prayervault:latest`, so the NAS never has to build.

1. On GitHub, create a Personal Access Token (classic) with the `read:packages` scope.
2. On the NAS: `docker login ghcr.io -u s39n -p <token>`
3. Copy `docker-compose.nas.yml`, `Caddyfile`, and a filled-in `.env` to the NAS.
4. In `.env`, point `PRAYERS_DIR` at the vault copy on the NAS and set
   `OLLAMA_URL=http://<lan-ip-of-ollama-machine>:11434` — `host.docker.internal`
   only works when Ollama runs on the same host. On the Ollama machine set
   `OLLAMA_HOST=0.0.0.0` so it accepts LAN connections.
5. `docker compose -f docker-compose.nas.yml up -d`

Update later with:
`docker compose -f docker-compose.nas.yml pull && docker compose -f docker-compose.nas.yml up -d`

> **Vault sync caution:** the app writes notes to whatever folder `PRAYERS_DIR` points
> at. On the NAS that must be a folder that syncs back into your vault (Syncthing /
> git pull job / SMB mount of the synced copy), or the notes will exist only on the NAS.
