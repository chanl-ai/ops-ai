# Security policy

## Supported versions

| Version | Security fixes |
|---|---|
| `main` | Yes. Fixes land here first |
| The latest release (the newest `vX.Y.Z` tag and its images on `ghcr.io/chanl-ai/ops-ai`) | Yes, in the next release |
| Older releases | No. Upgrade to the latest release |
| The SDKs (`ops-ai` on PyPI, `@chanl-ai/ops-ai` on npm) | The latest published version |

## Reporting a vulnerability

Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**
(GitHub private vulnerability reporting). Do not open a public issue, discussion or pull request for it.

Include what is affected (service, image or package, and the version or commit), how to reproduce it, and the impact
seen. A proof of concept helps; test only against systems you own.

| Step | When |
|---|---|
| The maintainers acknowledge the report | Within 3 business days |
| The issue is confirmed or ruled out, with a severity | Within 10 business days |
| A fix for a critical or high issue is released | Within 30 days of confirmation |
| A GitHub security advisory is published, crediting the reporter unless they ask otherwise | When the fix is released |

## How the code and releases are checked

Every scan, what it covers and how to verify a release yourself is in
[`docs/deploy/security-scanning.md`](docs/deploy/security-scanning.md).
