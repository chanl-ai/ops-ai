# Packages

Status: current.

The shared Python and TypeScript libraries the services and tools build on. A service page says what a service
does; a package page says what a library gives every service that uses it. Only the packages listed here have a
page of their own.

<!-- site: cards -->
| Package | What it gives |
|---|---|
| [Sign-in library](ops_signin/overview.md) | The protocols behind password, OIDC and SAML sign-in; the platform service is its one consumer |
| [Email library](ops_email/overview.md) | Mail in and out behind two protocols, with the provider picked by settings |
| [Source reading](ops_sources/overview.md) | One loop that reads a source through its tools: every page of changes since a saved place, paced fetches, gone-twice |
| [Knowledge ingestion](ops_ingest/overview.md) | Parsing, splitting, metadata mapping, dedupe and versions, and source rules for knowledge bases |
| [Logging](ops_service_kit/logging.md) | One JSON object per line on stdout from every Python service |
| [Use case runner](usecase-runner/overview.md) | Runs the use cases that prove each feature, by layer |

Libraries without a page here, such as the data layer and access rules, are described where they matter: in the
[architecture](../architecture/README.md) and the [engineering standards](../architecture/engineering-standards.md).
