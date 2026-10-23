/** The host an absolute request URL goes to, lower-cased; none while the URL is partial or its host is a {parameter}. */
export function hostOf(url: string): string | null {
  const m = /^https?:\/\/([^/:?#{}]+)(?::\d+)?(?:[/?#]|$)/i.exec(url.trim());
  return m ? m[1].toLowerCase() : null;
}
