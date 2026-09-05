# Deploying to Oracle Cloud (Always Free tier)

Single-VM deployment: `api` + `worker` + `web` (Next.js) + `caddy`
(automatic HTTPS), all on one Docker network, via `docker-compose.yml` at
the repo root. Good fit for the "small/beta, invite-only or a handful of
users" scale this was built for.

**Division of labor.** Everything under "What's already built" is done and
lives in this repo, ready to use. Everything under "What you do" needs a
human — an account, a payment method on file (even for the free tier),
clicking through a web console, and running commands over your own SSH
session. Nothing here can be done on your behalf without that access.

## What's already built

- `Dockerfile` (repo root) — api/worker image, already existed.
- `web/app/Dockerfile` — 3-stage Next.js standalone build.
- `docker-compose.yml` (repo root) — wires api, worker, web, and Caddy
  together, with a shared named volume for SQLite/caches/checkpoints.
- `Caddyfile` (repo root) — automatic HTTPS, `/backend/*` proxied to the
  API without colliding with Next.js's own `/api/*` routes.
- `.dockerignore` (root and `web/app/`) — keeps build contexts small and
  keeps real secrets out of image layers.
- `.env.production.example` (root) and `web/app/.env.production.example` —
  templates for the two secrets files the VM needs; copy and fill them in.

## What you do

### 1. Create an Oracle Cloud account

cloud.oracle.com → Start for free. Requires a payment method for identity
verification even though the Always Free shapes below cost nothing as long
as you stay within their limits — this step is yours to do; entering
payment details is outside what this session can do for you.

### 2. Provision the VM

Console → Compute → Instances → Create instance.

- **Shape**: `VM.Standard.A1.Flex` (Ampere, ARM), allocated generously —
  up to 4 OCPUs / 24 GB RAM is available on Always Free. **Take the RAM.**
  The binding constraint is not steady-state (the stack idles small); it
  is `npm run build` inside `web/app/Dockerfile`, which is the single
  most memory-hungry step in the whole deploy.

  **Do not use `VM.Standard.E2.1.Micro` (1 GB RAM) as a fallback.** An
  earlier draft of this document called it "tight but workable"; that is
  wrong. A Next.js production build will almost certainly be OOM-killed
  at 1 GB, and the failure looks like a mysteriously dead `docker build`
  rather than an out-of-memory error. If A1 capacity is unavailable in
  your region (a genuine and common Oracle Always Free friction point),
  the options are: wait for A1 capacity, or build the `web` image
  somewhere with more memory and push it to a registry, deploying only
  the prebuilt image on the micro instance.
- **Image**: Ubuntu (22.04 or 24.04 LTS) — Oracle's official image.
- **SSH key**: generate a new key pair in the console (download the
  private key) or paste your own public key. You'll need the private key
  to SSH in.
- Leave the VCN/subnet on the defaults the wizard creates — the next step
  fixes the one thing that needs changing there.

### 3. Open ports 80 and 443 — the Oracle-specific trap

Two independent firewalls sit in front of this VM, and both default to
blocking inbound 80/443. Missing either one looks identical from the
outside ("connection refused"/timeout), so fix both before assuming
anything else is wrong:

**a) The VCN Security List** (cloud-level, in front of the VM entirely).
Console → Networking → Virtual Cloud Networks → your VCN → Security Lists
→ Default Security List → Add Ingress Rules:
- Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port 443
- Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port 80

**b) The instance's own iptables.** Oracle's stock Ubuntu images ship
with iptables rules that also drop inbound traffic by default — a second,
OS-level gate the security list alone doesn't clear. SSH in and run:

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save   # persist across reboots; installed by default on Ubuntu images
```

(If `netfilter-persistent` isn't present, `sudo apt install iptables-persistent` first, or use `sudo iptables-save > /etc/iptables/rules.v4` if you know that path is already set up.)

### 4. Install Docker + Compose on the VM

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and back in (or `newgrp docker`) for the group change to take effect
docker compose version   # confirms the compose plugin is present
```

### 5. Get the code onto the VM

```bash
git clone <your-repo-url> tradingagents
cd tradingagents
git checkout main   # or whichever branch you're deploying
```

(If the repo is private, set up a deploy key or use `gh auth login` /
an HTTPS token — same as cloning any private repo.)

### 6. Fill in the two secrets files

```bash
cp .env.production.example .env.production
cp web/app/.env.production.example web/app/.env.production
```

Edit both with a real editor (`nano .env.production`) and fill in:

- **`.env.production`**: `DOMAIN`, `NEXT_PUBLIC_API_BASE_URL`, at least one
  LLM provider key (`OPENROUTER_API_KEY` matches the shipped default
  model), `TRADINGAGENTS_API_JWT_SECRET` (generate with
  `openssl rand -base64 32`), `TRADINGAGENTS_API_ALLOWED_ORIGINS` (JSON
  array of your real domain — see the file's own comment on why this
  isn't comma-separated), `TRADINGAGENTS_API_VAPID_SUBJECT`.
- **`web/app/.env.production`**: `NEXT_PUBLIC_API_BASE_URL` (same value as
  above), `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (a **production**
  OAuth client — see the file's comment for the exact redirect URI to
  register), `NEXTAUTH_SECRET` (must be byte-for-byte identical to
  `TRADINGAGENTS_API_JWT_SECRET` above — same secret, two names),
  `NEXTAUTH_URL`.

**No domain yet?** Use a free [sslip.io](https://sslip.io) address that
embeds your VM's public IP — Caddy can issue a real Let's Encrypt cert for
it since it's a resolvable DNS name, not a bare IP:

```
DOMAIN=203-0-113-10.sslip.io   # replace with your VM's actual public IP, hyphenated
```

Then `NEXT_PUBLIC_API_BASE_URL=https://203-0-113-10.sslip.io/backend` and
`NEXTAUTH_URL=https://203-0-113-10.sslip.io` to match.

If you do have a domain, point an A record at the VM's public IP instead
and use that.

### 7. First deploy

Every `docker compose` command below needs `--env-file .env.production`
explicitly. Reason: Compose reads two different things from that file —
`env_file:` entries in `docker-compose.yml` inject it into containers at
*runtime* regardless of flags, but `${DOMAIN}` and
`${NEXT_PUBLIC_API_BASE_URL}` written directly *inside* `docker-compose.yml`
(the `caddy` service's `environment:` and the `web` service's
`build.args:`) are resolved by Compose's own variable substitution, which
only reads a file literally named `.env` by default — not an `env_file:`
entry. Since this file is deliberately named `.env.production` (to stay
visually distinct from a dev checkout's `.env`), the flag is what makes
Compose look at it for substitution too. Omit it and `DOMAIN` silently
resolves to an empty string — Caddy gets a blank site block, not an error
you'd immediately connect to the cause.

```bash
docker compose --env-file .env.production config   # sanity-check first: prints the fully-resolved config; confirm DOMAIN and NEXT_PUBLIC_API_BASE_URL show real values, not blank
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps        # all 4 services should show "running"/"healthy"
docker compose --env-file .env.production logs -f caddy   # watch for the certificate to be issued (a few seconds to a couple minutes)
```

Visit `https://<your-domain>` — Caddy should present a valid cert and the
app should load.

### 8. Redeploy after a code change

```bash
git pull
docker compose --env-file .env.production up -d --build
```

`up -d --build` rebuilds and restarts every service together, every time —
this is the structural fix for the "code changed but the worker kept
running old code" problem this project hit twice during development
(described in `docker-compose.yml`'s top comment): there's no longer a
separate "restart the worker" step to forget.

### 9. Ongoing operations

```bash
docker compose --env-file .env.production logs -f api worker   # tail logs
docker compose --env-file .env.production down                 # stop everything (volumes persist)
docker compose --env-file .env.production down -v               # stop AND wipe the SQLite/cache/checkpoint volume — destructive, rarely what you want
```

Backups: everything durable (the runs DB, caches, LangGraph checkpoints)
lives in the `tradingagents_data` named volume. Back it up with:

```bash
docker run --rm -v tradingagents_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/tradingagents_data_$(date +%Y%m%d).tar.gz -C /data .
```

## Troubleshooting

- **Site unreachable, no TLS error at all**: almost always one of the two
  firewalls in Step 3. Test with `curl -v http://<vm-public-ip>` from your
  own machine; a hang/timeout points at the VCN security list, an
  immediate refusal from inside the VM itself
  (`curl -v http://localhost` on the VM) points at iptables.
- **Caddy logs show a certificate error**: `DOMAIN` isn't resolving to
  this VM yet (DNS propagation, or a typo'd sslip.io IP), or ports 80/443
  aren't actually reachable from the public internet yet — Let's Encrypt's
  HTTP-01 challenge needs a real inbound connection to succeed.
- **Sign-in fails / CORS errors in the browser console**:
  `TRADINGAGENTS_API_ALLOWED_ORIGINS` doesn't match the origin you're
  browsing from exactly (scheme + host, no trailing slash), or
  `NEXTAUTH_SECRET` / `TRADINGAGENTS_API_JWT_SECRET` don't match
  byte-for-byte.
- **`docker compose config` shows blank values for DOMAIN or
  NEXT_PUBLIC_API_BASE_URL**: you forgot `--env-file .env.production` on
  that command — see Step 7's explanation.
