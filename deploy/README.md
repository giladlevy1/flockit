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

`FLOCKIT_PUBLIC_URL` matters: it is baked into the install command on the Connect page. Leave it empty
and Flockit uses whatever address the admin's browser used, which is wrong if that was `localhost`.

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

## 6. Verifying zero egress

`./deploy/network-trace.sh 300` captures every packet the deployment sends for five minutes and reports
anything that leaves the compose network. See [docs/network-trace.md](../docs/network-trace.md) for our
own results.
