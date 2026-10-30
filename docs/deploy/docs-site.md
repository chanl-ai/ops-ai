# The docs site on Vercel

Status: current. The site can deploy from the repository's main branch to any static host; this page uses Vercel as the example.

The docs site (`apps/docs`) builds `docs/` and the services' OpenAPI files into static files under `/docs`. It needs no
server and no secrets, so any static host can serve it. This is how a Vercel project is set up for it.

| Setting | Value | Why |
|---|---|---|
| Project | `<your-project>`, in your Vercel team | |
| Repository | your clone or fork, production branch `main` | Every push to main deploys; pull requests get preview deployments |
| Domain | `<docs-domain>` | If the domain's DNS is on Vercel in the same team, adding it to the project creates its record; otherwise add the record Vercel shows |
| Root Directory | `apps/docs` | `apps/docs/vercel.json` sets the build command, the output folder and the `/docs` routes |
| Include files outside the root directory in the Build Step | On | The site reads `../../docs` and `../../services` |
| Framework Preset | Other | The build is a static export (`out/`), served by `vercel.json` |
| Install Command | default | Vercel runs `pnpm install` at the workspace root from `pnpm-lock.yaml` |
| Build Command | default (`pnpm build` from `vercel.json`) | Runs the link check and the diagram check, then `next build` |
| Output Directory | default (`out` from `vercel.json`) | |
| Node.js | 22.x | |
| Environment variables | none | GitHub links use the deployed commit (`VERCEL_GIT_COMMIT_SHA`) |
| Ignored Build Step | Not set | `git diff --quiet HEAD^ HEAD -- docs services apps/docs pnpm-lock.yaml` would skip commits that change neither the docs nor the site, and it also skips a first deploy of such a commit |

The site answers at `https://<docs-domain>/docs`; `/` redirects there. To show it at `/docs` on another host later,
that host adds one rewrite from `/docs/:path*` to `https://<docs-domain>/docs/:path*`.

Check a build locally before pushing: `pnpm --filter docs build` must exit 0. Vercel installs with a frozen lockfile, so a
changed dependency in `apps/docs/package.json` needs `pnpm-lock.yaml` updated in the same commit.
