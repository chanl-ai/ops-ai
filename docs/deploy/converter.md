# The converter worker

Status: current. Proven locally; not yet run on a client's servers. Optional: without it Word files and decks show
text only.

The converter draws a `.docx` or `.pptx` file as a PDF so documents-service can show it as pages. It is a small
separate container (the `converter` target of `deploy/fly/Dockerfile`, code in `deploy/images/converter`) that runs
LibreOffice, which is licensed MPL-2.0. It accepts only those
two file types.

## What it does

| Request | Answer |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `POST /convert?name=<file name>`, the raw bytes as the body | `200 application/pdf` |
| A name that does not end in `.docx` or `.pptx` | `415` |
| A body over 50 MB | `413` |
| Bytes that are not a zip file, or a file LibreOffice cannot open | `422` |
| A conversion over 90 seconds | `504`; LibreOffice and every process it started are killed |
| A drawing over 200 MB | `422` |

One conversion runs at a time; a second request waits. Each conversion gets a fresh temporary folder and its own
LibreOffice profile. Decks are exported with their hidden slides, so slide N of a deck is page N of the PDF.

## What it can reach

The container needs no network: documents-service sends it the bytes and takes the PDF back. It holds no settings,
keys or database login. documents-service waits for files-service to scan each drawing clean before it shows it.

| Limit | Compose | Kubernetes | Dev (`make converter-up`) |
|---|---|---|---|
| Network in | `documents` only, on the internal `converter` network; no published port | NetworkPolicy `converter-isolated`: ingress from `documents` pods on 8770 only | `127.0.0.1:8780+offset`, through a relay container |
| Network out | None: the network is `internal: true` | None: the policy's egress list is empty, DNS included | None: the converter's network is `--internal`; only the relay, which runs no LibreOffice, is also on the host's |
| Filesystem | Read-only root; tmpfs `/tmp` 512 MB and `/home/ops` 256 MB | Read-only root; emptyDir `/tmp` and `/home/ops`, 512 MB each | Read-only root; tmpfs as Compose |
| User | uid 10001, every capability dropped, no new privileges | uid 10001, RuntimeDefault seccomp, every capability dropped, no service account token | As Compose |
| Memory and processes | 1 GB, 256 processes | 1 Gi | 1 GB, 256 processes |
| Time and size | 50 MB in, 200 MB out, 90 s per file (`OPS_CONVERTER_TIMEOUT_S`) | Same | Same |

NetworkPolicy holds only where the cluster's network plugin enforces it. Kubernetes has no per-pod process limit; the
node's `podPidsLimit` applies.

## Turn it on in Compose

The service is in the `converter` profile, so an install that does not turn it on needs no extra image.

1. Build or load the `converter` image (`docker compose -f app.yaml -f build.yaml --profile converter build converter`
   from a checkout).
2. Set `OPS_DOCUMENTS_CONVERTER_URL=http://converter:8770` in the env file. Empty means off.
3. Start with `--profile converter`.

## Turn it on in the dev stack

```
make converter-up              # builds the image once, runs ops-converter-<offset> behind a relay on 127.0.0.1:8780+offset
make up CONVERTER=1            # documents-service gets OPS_DOCUMENTS_CONVERTER_URL
make converter-down
```

The host port is 8780 plus `OPS_PORT_OFFSET` (8770 belongs to the code runner). A documents-service that is already
running keeps its old settings until `make restart CONVERTER=1`. The default stays off.

## Kubernetes and the release package

The base (`deploy/k8s/base/converter`) runs it and points documents at `http://converter:8770`, so every cluster draws
Word files and decks. The release package builds and loads the `converter` image with the other services.
