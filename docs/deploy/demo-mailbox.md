# Demo mailbox on Fly

Status: current. This page describes a demo mailbox such as `notices@<mail-domain>`, a real mailbox anyone can email from any mail client. Your staging instance (https://<your-app>.fly.dev) reads it over IMAP with the existing IMAP connector, so a demo can start from a
real email instead of an upload. It only receives: Fly blocks outbound port 25, so nothing is relayed or sent from it.

## What runs where

| Part | Where | Notes |
|---|---|---|
| Mail server | Fly app `<app-prefix>-mail` (your Fly org, one region), one shared-cpu-1x machine with 512 MB, always on | Stalwart Mail Server v0.16.27; SMTP in on 25, SMTP over TLS on 465, IMAP over TLS on 993, ACME on 443 |
| Address | A dedicated IPv4 and IPv6 address, allocated with `fly ips allocate-v4` and `fly ips allocate-v6` | Plain SMTP has no SNI, so a shared Fly IPv4 cannot route it |
| Data | Volume `mail_data` (1 GB) at `/data`: `/data/etc/config.json` and the RocksDB store in `/data/db` | |
| TLS | Let's Encrypt certificate for `mx.<mail-domain>`, obtained and renewed by Stalwart (TLS-ALPN-01 on 443) | |
| DNS | Your DNS provider, zone `<mail-domain>` | Add only the records below |

| Record | Type | Value |
|---|---|---|
| `<mail-domain>` | MX | `10 mx.<mail-domain>` |
| `<mail-domain>` | TXT | `v=spf1 -all` (nothing sends as this domain) |
| `mx.<mail-domain>` | A | `<dedicated IPv4>` |
| `mx.<mail-domain>` | AAAA | `<dedicated IPv6>` |

Fly forwards each port as raw TCP with the PROXY protocol (v2), so Stalwart sees the sender's real address; the
public listeners trust the header only from Fly's proxy networks (`172.16.0.0/12`, `fdaa::/16`). The spam filter is
off, so every message lands in INBOX, the one folder the connector reads.

Ops AI side: `mx.<mail-domain>` goes on the tenant's egress allow-list (Security team). The list holds
hosts only; the IMAP connector dials 993 over TLS by default.

## Secrets

| Value | Kept in |
|---|---|
| Mailbox password for `notices@<mail-domain>` | a private file (mode 600) on the maintainer's machine; nowhere else until it is typed into Channels > Email |
| Stalwart admin password | Fly secret `STALWART_RECOVERY_ADMIN` on `<app-prefix>-mail`, and a private env file (mode 600) |

The deploy files (`Dockerfile`, `entrypoint.sh`, `fly.toml`, `configure.py`) are in
a private deploy directory. The image is the stock Stalwart image with an entrypoint that hands the
root-owned Fly volume to the `stalwart` user and starts the server with `--config /data/etc/config.json`.

## Connect it in the console

Channels > Email > Connect mailbox: IMAP host `mx.<mail-domain>`, port 993, user `notices@<mail-domain>`, the
password from the file above (as a Secrets-page secret). No SMTP host is needed to read.

## Send a test

From any mail client, write to `notices@<mail-domain>`. Without a mail client, send straight to the MX on port 25
(needs a network that allows outbound 25; most home and office networks do, Fly does not):

```
swaks --to notices@<mail-domain> --server mx.<mail-domain> --port 25 --header "Subject: demo test"
```

Read it back with Python's `imaplib.IMAP4_SSL("mx.<mail-domain>", 993)`, signing in with the address and the password.

## Admin and password rotation

The admin API listens only on the private network: `fly proxy 18081:8080 -a <app-prefix>-mail`, then the
`stalwart-cli` (github.com/stalwartlabs/cli) with `STALWART_URL=http://127.0.0.1:18081`.

To rotate the mailbox password: write a new value into the private password file
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
| DKIM, DMARC for `<mail-domain>` | Not set: the domain sends nothing |
| Backups | None; the mailbox holds demo mail only |
| Certificate renewal | Scheduled by Stalwart ahead of expiry. An ACME task left pending across a restart did not run once; setting the domain's certificate management to Manual and back to Automatic (`stalwart-cli update Domain <id>`) queued a fresh order, which succeeded |
| `Proxy protocol error: end of stream` in the logs every 30 s | Fly's TCP health check on 25 connects without a PROXY header; harmless |
