/**
 * The build's version as the What's new header shows it: the release tag when the built commit carries one
 * (`v1.2.0`, made when a release merges into main by `make release-tag`; installs from before that carry date tags such as `v2026-10-23.1`), else the branch and short commit. Both are written in
 * at build time (next.config.ts); a build with neither shows nothing rather than a guess.
 */
export function versionLabel(tag: string | undefined, commit: string | undefined): string | null {
  const t = tag?.trim();
  if (t) return t;
  const c = commit?.trim();
  return c ? `main · ${c}` : null;
}
