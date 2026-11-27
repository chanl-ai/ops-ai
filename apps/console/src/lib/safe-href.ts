/**
 * A link address from stored or model-written data, kept only when it is a console path or a web or mail link. A
 * `javascript:` or `data:` address would run in the console's origin when clicked or framed.
 */
export function safeHref(href: string | undefined, { web = false }: { web?: boolean } = {}): string | undefined {
  if (!href) return undefined;
  const trimmed = href.trim();
  if (/^https?:\/\//i.test(trimmed)) return href;
  if (web) return undefined;
  if (/^mailto:/i.test(trimmed)) return href;
  return consolePath(trimmed) ? href : undefined;
}

/**
 * A link address kept only when it is a path in this console: card data never sends a click to another host. A path
 * starting `//` or `/\` is read by browsers as another host, and control characters can hide either.
 */
export function consolePath(href: string | undefined): string | undefined {
  if (!href || /[\u0000-\u001f\u007f]/.test(href)) return undefined;
  return /^\/(?![/\\])/.test(href) ? href : undefined;
}
