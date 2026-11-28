/**
 * The build's version as the What's new header shows it: the release tag when the built commit carries one
 * (`v1.2.0`, made when a release merges into main, by release-finish.yml; installs from before that carry date tags such as `v2026-10-23.1`), else the branch it was built from and the short commit, or the commit alone when the branch is unknown. Both are written in
 * at build time (next.config.ts); a build with neither shows nothing rather than a guess.
 */
export function versionLabel(tag: string | undefined, commit: string | undefined, branch?: string): string | null {
  const t = tag?.trim();
  if (t) return t;
  const c = commit?.trim();
  if (!c) return null;
  const b = branch?.trim();
  return b ? `${b} · ${c}` : c;
}
