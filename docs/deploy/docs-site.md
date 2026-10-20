# The docs site on Vercel

Status: current. The Vercel project is not created yet.

The docs site (`apps/docs`) builds `docs/` and the services' OpenAPI files into static files under `/docs`. It needs no
server and no secrets, so any static host can serve it; these are the steps for Vercel.

| Setting | Value | Why |
|---|---|---|
| Repository | `chanl-ai/ops-ai`, production branch `main` | |
| Root Directory | `apps/docs` | `apps/docs/vercel.json` sets the build command, the output folder and the `/docs` routes |
| Include files outside the root directory in the Build Step | On | The site reads `../../docs` and `../../services` |
| Framework Preset | Other | The build is a static export (`out/`), served by `vercel.json` |
| Install Command | default | Vercel runs `pnpm install` at the workspace root from `pnpm-lock.yaml` |
| Build Command | default (`pnpm build` from `vercel.json`) | Runs the link check and the diagram check, then `next build` |
| Output Directory | default (`out` from `vercel.json`) | |
| Node.js | 22.x | |
| Environment variables | none | GitHub links use the deployed commit (`VERCEL_GIT_COMMIT_SHA`) |
| Ignored Build Step (optional) | `git diff --quiet HEAD^ HEAD -- docs services apps/docs pnpm-lock.yaml` | Skips commits that change neither the docs nor the site |

The site answers at `https://<project>.vercel.app/docs`; `/` redirects there. To show it at `/docs` on another
host later, that host adds one rewrite from `/docs/:path*` to `https://<project>.vercel.app/docs/:path*`.

Check a build locally before connecting the project: `pnpm --filter docs build` must exit 0.
