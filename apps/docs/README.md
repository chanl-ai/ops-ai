# Docs site

The Ops AI docs site: a Fumadocs app served under `/docs` that presents `docs/` and each `services/*/openapi.json`
as they are in this repository. Its conventions for authors are in `docs/README.md`, "How the docs site shows a page".

```
pnpm install
pnpm --filter docs build      # link check, diagram check, static export to apps/docs/out
pnpm --filter docs dev        # http://localhost:3040/docs
pnpm --filter docs diagrams   # export docs/diagrams/*.yaml to their SVGs after editing one
```

`pnpm --filter docs build` fails on a link to a page or file that does not exist and on a diagram SVG that no longer
matches its data file. The output is static (`out/`); `vercel.json` serves it under `/docs`. Hosting it on Vercel:
`docs/deploy/docs-site.md`.
