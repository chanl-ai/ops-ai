# Demo mailbox for staging

Status: current (c-467). `notices@ops.mails.run` is a real mailbox anyone can email from any mail client. Staging
(https://<your-app>-one.fly.dev) reads it over IMAP with the existing IMAP connector, so a demo can start from a
real email instead of an upload. It only receives: Fly blocks outbound port 25, so nothing is relayed or sent from it.

## What runs where

| Part | Where | Notes |
|---|---|---|
| Mail server | Fly app `<your-app>-mail` (org `<your-org>`, region ewr), one shared-cpu-1x machine with 512 MB, always on | Stalwart Mail Server v0.16.27; SMTP in on 25, SMTP over TLS on 465, IMAP over TLS on 993, ACME on 443 |
| Address | Dedicated IPv4 `137.66.25.105`, IPv6 `2a09:8280:1::1c3:7c52:0` | Plain SMTP has no SNI, so a shared Fly IPv4 cannot route it |
| Data | Volume `mail_data` (1 GB) at `/data`: `/data/etc/config.json` and the RocksDB store in `/data/db` | |
| TLS | Let's Encrypt certificate for `mx.ops.mails.run`, obtained and renewed by Stalwart (TLS-ALPN-01 on 443) | |
| DNS | Vercel DNS, zone `mails.run` | Added only these; the root and `stg` records belong to another product |

| Record | Type | Value |
|---|---|---|
| `ops.mails.run` | MX | `10 mx.ops.mails.run` |
| `ops.mails.run` | TXT | `v=spf1 -all` (nothing sends as this domain) |
| `mx.ops.mails.run` | A | `137.66.25.105` |
| `mx.ops.mails.run` | AAAA | `2a09:8280:1::1c3:7c52:0` |

Fly forwards each port as raw TCP with the PROXY protocol (v2), so Stalwart sees the sender's real address; the
public listeners trust the header only from Fly's proxy networks (`172.16.0.0/12`, `fdaa::/16`). The spam filter is
off, so every message lands in INBOX, the one folder the connector reads.

Ops AI side: `mx.ops.mails.run` is on the tenant's egress allow-list (Security team, added 2026-10-21). The list holds
hosts only; the IMAP connector dials 993 over TLS by default.

## Secrets

| Value | Kept in |
|---|---|
| Mailbox password for `notices@ops.mails.run` | `~/.config/ops-ai/staging-mail-notices.txt` (mode 600) on the maintainer's machine; nowhere else until it is typed into Channels > Email |
| Stalwart admin password | Fly secret `STALWART_RECOVERY_ADMIN` on `<your-app>-mail`, and `~/.config/ops-ai/staging-mail-admin.env` (mode 600) |

The deploy files (`Dockerfile`, `entrypoint.sh`, `fly.toml`, `configure.py`) are in
`~/.config/ops-ai/staging-mail-deploy/`. The image is the stock Stalwart image with an entrypoint that hands the
root-owned Fly volume to the `stalwart` user and starts the server with `--config /data/etc/config.json`.

## Connect it in the console

Channels > Email > Connect mailbox: IMAP host `mx.ops.mails.run`, port 993, user `notices@ops.mails.run`, the
password from the file above (as a Secrets-page secret). No SMTP host is needed to read.

## Send a test

From any mail client, write to `notices@ops.mails.run`. Without a mail client, send straight to the MX on port 25
(needs a network that allows outbound 25; most home and office networks do, Fly does not):

```
swaks --to notices@ops.mails.run --server mx.ops.mails.run --port 25 --header "Subject: demo test"
```

Read it back with Python's `imaplib.IMAP4_SSL("mx.ops.mails.run", 993)`, signing in with the address and the password.

## Admin and password rotation

The admin API listens only on the private network: `fly proxy 18081:8080 -a <your-app>-mail`, then the
`stalwart-cli` (github.com/stalwartlabs/cli) with `STALWART_URL=http://127.0.0.1:18081`.

To rotate the mailbox password: write a new value into `~/.config/ops-ai/staging-mail-notices.txt`
(`openssl rand -base64 33 | tr -d '/+=' | cut -c1-32`), run
`STALWART_URL=http://127.0.0.1:18081 STALWART_CLI=<path to stalwart-cli> python3 configure.py configure` from the
deploy directory (it re-applies the account with the file's password and changes nothing else), then update the
Secrets-page secret the mailbox uses in Ops AI.

## Cost

Fly list prices: shared-cpu-1x with 512 MB about 3.19 USD a month, the dedicated IPv4 2.00 USD, the 1 GB volume
0.15 USD: about 5.35 USD a month. The machine never stops, since mail servers retry but do not wait for a cold start.
Unverified against an invoice.

## Not covered

| Item | State |
|---|---|
| Sending replies | Not possible from Fly (outbound 25 blocked); replies go through the staging mail provider, which is `none` |
| DKIM, DMARC for `ops.mails.run` | Not set: the domain sends nothing |
| Backups | None; the mailbox holds demo mail only |
| Certificate renewal | Scheduled by Stalwart for 2026-12-20 (the first certificate expires 2027-01-19). An ACME task left pending across a restart did not run on 2026-10-21; setting the domain's certificate management to Manual and back to Automatic (`stalwart-cli update Domain <id>`) queued a fresh order, which succeeded in 8 s |
| `Proxy protocol error: end of stream` in the logs every 30 s | Fly's TCP health check on 25 connects without a PROXY header; harmless |
