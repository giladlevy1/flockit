# Network trace: Flockit makes no outbound calls

Flockit's promise is that nothing leaves your network: no telemetry, no analytics, no update check,
no license check. This page records how we verified it, so you can repeat it on your own deployment.

## Method

Captured on 2026-09-19 against a fresh `docker compose up` of commit `b11b763` (the first release commit; later commits did not change the server's network behaviour) (Docker Desktop, macOS).

Three `tcpdump` captures ran at the same time:

| Capture | Where | Why |
|---|---|---|
| `app.pcap` | inside the Flockit container's network namespace, all interfaces | everything the server process sends, including loopback and DNS |
| `db.pcap` | inside the Postgres container's network namespace | the database must not talk to anything but the app |
| `bridge.pcap` | on the compose network's bridge, from the Docker host | survives container restarts, so it also covers server **startup**, when software typically phones home |

During the capture window (about 3 minutes) we exercised everything:

- signed in and browsed every page of the UI (Sessions with several filters, session detail, People,
  Connect), with the UI's 5-second live polling running throughout;
- ran a real Claude Code 2.1.220 session through the collector, and flushed its outbox;
- restarted the Flockit container (migrations, startup, the abandoned-session sweeper);
- left it idle for 60 seconds after startup.

The `tcpdump` image was built **before** the capture, so installing it generated no traffic in these
namespaces.

## Results

| Check | Result |
|---|---|
| TCP connections opened by the Flockit server | **only to Postgres** (`172.21.0.2:5432`) |
| UDP datagrams sent by the Flockit server | none, apart from Docker's embedded resolver (`127.0.0.11`), asked once for `db` |
| Connections opened by Postgres | **none** |
| Packets from the server to any public address, excluding replies to inbound `:8080` connections | **0** |
| Origins loaded by the browser UI (114 resources) | **one**: the Flockit server itself |

One address in the capture needed checking: `151.101.2.132`. Every packet involving it is an inbound
connection **to** the server on `:8080` carrying the UI's own requests (`GET /api/sessions…`). It is the
source address Docker Desktop's port forwarder gives to connections from the host, not a destination the
server contacted: all 12 SYNs in the capture go from it to `:8080`, and none go the other way.

The browser side is also enforced, not just observed. Every response carries
`Content-Security-Policy: default-src 'self'; connect-src 'self'; …`, and the fonts are bundled into the
build, so the page cannot load anything from another origin.

## The collector

The collector on each developer machine talks to exactly one host: the server URL the developer
configured. All of its network code is in
[`collector/src/flockit/transport.py`](../collector/src/flockit/transport.py) (about 80 lines, standard
library only). It has no dependencies, so there is no third-party code that could make calls of its own.

## Repeat it yourself

```bash
docker compose up -d
./deploy/network-trace.sh 300   # use Flockit normally for 5 minutes while it captures
```

The script prints every destination the server opened a connection to, and the count of packets
addressed to public IPs. On a correct deployment the first list contains only the database and the
count is `0`.
