# Running Flockit in production

The root `docker-compose.yml` is the production deployment: one app container, one Postgres container,
nothing else. This page covers what changes when it runs for a real team.

## 1. Settings

Copy `.env.example` to `.env` and set at least:

```bash
POSTGRES_PASSWORD=<a long random value, before the first start>
FLOCKIT_PUBLIC_URL=https://flockit.internal.example.com   # what developer laptops use to reach Flockit
FLOCKIT_SECURE_COOKIES=true                               # once it is served over HTTPS
```

`FLOCKIT_PUBLIC_URL` matters: it is baked into the install command on the Connect page. Without it,
Flockit records the address the admin used during first-run setup (admins can change it on the Connect
page). That is wrong if setup happened over `localhost`, so set it explicitly in production. Ordinary
requests' `Host` headers are never used once either value exists.

## 2. HTTPS

Terminate TLS in the reverse proxy you already run. Example for nginx:

```nginx
server {
    listen 443 ssl;
    server_name flockit.internal.example.com;
    ssl_certificate     /etc/ssl/flockit.crt;
    ssl_certificate_key /etc/ssl/flockit.key;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

If the proxy runs on another host, set `FLOCKIT_FORWARDED_ALLOW_IPS` on the `flockit` service to its
address so forwarded headers are trusted.

Avoid proxies that fetch certificates from the internet on their own if your policy is zero egress;
Flockit itself never needs outbound access.

## 3. Backups

All state is in Postgres. A nightly logical backup is enough for most teams:

```bash
docker compose exec -T db pg_dump -U flockit -Fc flockit > flockit-$(date +%F).dump
# restore into a fresh deployment:
docker compose exec -T db pg_restore -U flockit -d flockit --clean < flockit-2026-09-19.dump
```

## 4. Upgrades

```bash
git pull
docker compose up -d --build
```

Migrations run automatically when the app container starts. Collectors keep buffering while the server
restarts, so no sessions are lost during an upgrade.

## 5. Admin recovery

Locked out? Create or reset an admin from the host:

```bash
docker compose exec flockit flockit-server create-admin --email you@example.com
```

## 6. Runners for AI developers

A runner is any machine in your network with Docker. It needs outbound access to your model provider and git host; the
Flockit server still does not.

```bash
curl -fsSL https://flockit.internal.example.com/install.sh | sh -s -- --runner-only
~/.flockit/venv/bin/flockit runner build-image          # Claude Code + Codex inside a node:22 image

export ANTHROPIC_API_KEY=...        # or CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) for Claude Code
export OPENAI_API_KEY=...           # for Codex AI developers
export GH_TOKEN=...                 # clone private repos, push branches, open pull requests
~/.flockit/venv/bin/flockit runner --server https://flockit.internal.example.com --token frn_... --capacity 2
```

- Each task runs in a new container (`--memory 4g --cpus 2 --pids-limit 512`), removed afterwards. Credentials are passed by
  name from the runner's environment, never on the command line.
- Pools: give a runner `--pool` (set when you create it in the UI) and an AI developer the same pool to pin its work there.
- Git hosts reached over SSH: `--clone-url 'git@{host}:{path}.git'`.
- Keep it running with systemd, a container, or your process manager of choice.

## 7. Verifying zero egress

`./deploy/network-trace.sh 300` captures every packet the deployment sends for five minutes and reports
anything that leaves the compose network. See [docs/network-trace.md](../docs/network-trace.md) for our
own results.
