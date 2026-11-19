# Website

Status: current. Ships with Ops AI; no sign-in.

Public help pages, rate sheets and product terms change on your website first. The Website source keeps a knowledge
base current with them, so agents quote today's page and cite it. It follows a site's sitemaps and links, within rules
you set, and respects the site's robots.txt.

## Add a website source

<!-- site: steps -->
1. **Add the source.** In **Knowledge**, open a knowledge base, press **Add source** and pick Website. Give the start
   pages or sitemap addresses of one site.
2. **Set the rules**: include and exclude paths such as `/lending/**` and `/archive/**`, how deep to follow links, and
   the most pages to take.
3. **Preview.** The preview lists the first pages the source would take in, each with its outcome (fetched, excluded
   by a rule, refused by robots.txt). Nothing is stored yet.
4. **Get the host approved.** A site whose host is not on the egress list waits: the source reads **Waiting for an
   admin to approve** the host. A Security admin adds it in **Settings › Security › Egress**.
5. **Create and sync.** The **Documents** tab lists each page as it is indexed.

Expected: pages matching the rules are indexed; excluded pages and pages robots.txt refuses are never requested. Ask
the base's Playground about a page and the answer cites it.

## Source options

| Option | What it does | Default |
|---|---|---|
| Start pages | Start pages or sitemap addresses, all on one site | Required |
| Follow links | Follow links from the pages it reads, as well as sitemaps | Optional |
| Depth | How many links deep to follow | Optional |
| Most pages | A cap on the pages taken in | Optional |
| Include, exclude | Path patterns; exclude wins | Everything, nothing |
| Rate | Requests per second to the site | Optional |
| Schedule | When the source syncs | Daily at 02:00 |

## How syncs keep it current

| At the site | On the next sync |
|---|---|
| A page changes | Only that page is fetched again, and becomes a new version |
| A page leaves the sitemap | It leaves the base and search |
| A page answers 404 | It stays after the first miss and is removed after the second |

## Limits

- One site per source. Add a source per site.
- Pages behind a sign-in cannot be read.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base end to end.
- [Integrations](overview.md): every app Ops AI ships with.
