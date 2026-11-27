# The converter worker

Status: current. Proven locally; not yet run on a client's servers. Optional: without it Word files and decks show
text only.

The converter draws a `.docx` or `.pptx` file as a PDF so documents-service can show it as pages. It is a small
separate container (`deploy/images/converter`) that runs LibreOffice, which is licensed MPL-2.0. It accepts only those
two file types.

## What it does

| Request | Answer |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `POST /convert?name=<file name>`, the raw bytes as the body | `200 application/pdf` |
| A name that does not end in `.docx` or `.pptx` | `415` |
| A body over 50 MB | `413` |
| Bytes that are not a zip file, or a file LibreOffice cannot open | `422` |
| A conversion over 90 seconds | `504` |

One conversion runs at a time; a second request waits. Each conversion gets a fresh temporary folder and its own
LibreOffice profile. Decks are exported with their hidden slides, so slide N of a deck is page N of the PDF.

## No network access

The container needs no network: documents-service sends it the bytes and takes the PDF back.

| Target | How it is kept off the network |
|---|---|
| Compose | The `converter` service is on a network marked `internal: true` that only it and `documents` share, and publishes no port |
| Dev | The container runs read-only with every capability dropped and publishes only `127.0.0.1`. Dev publishes a port so the host processes can reach it, so it is not network-isolated; use it for trying, not for real files |
| Kubernetes | Not added. Give the converter its own Deployment and a NetworkPolicy that allows ingress from documents only and no egress |

## Turn it on in Compose

The service is in the `converter` profile, so an install that does not turn it on needs no extra image.

1. Build or load the `converter` image (`docker compose -f app.yaml -f build.yaml --profile converter build converter`
   from a checkout).
2. Set `OPS_DOCUMENTS_CONVERTER_URL=http://converter:8770` in the env file. Empty means off.
3. Start with `--profile converter`.

## Turn it on in the dev stack

```
make converter-up              # builds the image once, runs ops-converter-<offset> on 127.0.0.1:8780+offset
make up CONVERTER=1            # documents-service gets OPS_DOCUMENTS_CONVERTER_URL
make converter-down
```

The host port is 8780 plus `OPS_PORT_OFFSET` (8770 belongs to the code runner). A documents-service that is already
running keeps its old settings until `make restart CONVERTER=1`. The default stays off.

## Not yet covered

The release package (`deploy/release/images.sh`, `package.sh`) and the mirror lane do not build or load the converter
image yet, so a package install cannot turn it on until they do.
