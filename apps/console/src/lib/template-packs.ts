/**
 * The template pack that brings a kind of template, for the gallery's empty state. A pack is no app a person connects,
 * so the Apps list leaves it out (tools-service apps.py) and its own page is where an admin turns it on.
 * Only the starters pack brings a kind the gallery lists; the other kinds come from apps, which Connectors lists.
 */
const PACK_OF_KIND: Record<string, { app: string; name: string }> = {
  skill: { app: 'plugin:opsai.starters', name: 'Starter skills' },
};

/** The pack to turn on for a kind of template, with the address of its page; null when apps bring that kind. */
export function packFor(kind: string): { name: string; href: string } | null {
  const pack = PACK_OF_KIND[kind];
  return pack ? { name: pack.name, href: `/data/connectors/${encodeURIComponent(pack.app)}` } : null;
}
