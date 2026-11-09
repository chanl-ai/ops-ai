/**
 * The console page of an app (src/app/integrations/apps/[id]): an app id such as `plugin:<id>`, or a connection id,
 * which the page resolves to its app. Every link to an app page is built here, so none can drop the `apps/` segment
 * or leave the id unencoded.
 */
export function appPageHref(id: string, tab?: string): string {
  const path = `/integrations/apps/${encodeURIComponent(id)}`;
  return tab ? `${path}?tab=${encodeURIComponent(tab)}` : path;
}
