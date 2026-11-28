# Website

Status: current.

Your public help pages, rate sheets and product terms change on your website first. An agent that answers from a copy
pasted months ago quotes the old rate. A website source keeps a knowledge base current with the pages you pick, so agents
quote today's page and cite it. The source follows the site's sitemaps, and its links if you ask it to, within the rules
you set. It never requests a page that the site's robots.txt refuses. You don't need to sign in to anything.

## Add a website source

<!-- site: steps -->
1. **Add the source.** In **Knowledge bases**, open a knowledge base, press **Add data source** and choose **Website or sitemap**. Enter the start
   pages or sitemap addresses of one site.
2. **Set the rules.** Add include and exclude paths such as `/lending/**` and `/archive/**`, how many links deep to
   follow, and the most pages to take in.
3. **Get the host approved.** If the site's host is not on the egress list, the source reads **Waiting for an admin to
   approve** the host. A Security admin adds it in **Settings › Security › Egress**.
4. **Preview.** The preview lists the first pages the source would take in, each with its outcome: fetched, excluded by a
   rule, refused by robots.txt, or needing JavaScript. Nothing is stored yet.
5. **Create and sync.** The **Documents** tab lists each page as it is indexed.

## Check what the source took in

Pages that match your rules are indexed. Pages you excluded, and pages that robots.txt refuses, are never requested. Ask
the knowledge base's **Test** panel about a page and the answer cites it. Each later sync reads only what changed, so a
rate change on your site reaches the agent at the next sync.

If you skip the preview, a rule that is too wide or too narrow shows up only after the whole sync has run.

## Source options

| Option | What it does | Default |
|---|---|---|
| Start pages | Start pages or sitemap addresses, all on one site | Required |
| Follow links | Follows links from the pages it reads, as well as the sitemaps | Off |
| Depth | How many links deep to follow, from 1 to 5 | 2 |
| Most pages | A cap on the pages taken in, up to 5000 | 500 |
| Include, exclude | Path patterns, where exclude wins | Everything, nothing |
| Rate | Requests per second to the site, from 0.2 to 5. The site's robots.txt Crawl-delay can make it slower | 1 |
| Schedule | When the source syncs | Daily at 02:00 |

## How syncs keep it current

<!-- site: decision caption="What the next sync does with a page, by what happened at the site" -->
- **What happened to the page?**
  - **It changed**: Only that page is fetched again, and it becomes a new version.
  - **It left the sitemap**: It leaves the knowledge base and search.
  - **It answers 404 or 410**: It stays after the first miss and is removed after the second.

## Pages the source cannot read

- Each source covers one site. Add a source for each site.
- Pages behind a sign-in cannot be read.
- A page that shows its text only through JavaScript is flagged in the preview, and the source does not run JavaScript.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base from start to finish.
- [Integrations](overview.md): every app Ops AI ships with.
