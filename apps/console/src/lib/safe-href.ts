/**
 * A link address from stored or model-written data, kept only when it is a console path or a web or mail link. A
 * `javascript:` or `data:` address would run in the console's origin when clicked or framed.
 */
export function safeHref(href: string | undefined, { web = false }: { web?: boolean } = {}): string | undefined {
  if (!href) return undefined;
  const allowed = web ? /^https?:\/\//i : /^(\/(?!\/)|https?:\/\/|mailto:)/i;
  return allowed.test(href.trim()) ? href : undefined;
}
