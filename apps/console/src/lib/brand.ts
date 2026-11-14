/**
 * The console's accent colour for a demo, from OPS_BRAND_PRIMARY (and OPS_BRAND_PRIMARY_DARK) in .env, with no code
 * change. Only a plain CSS colour is accepted, so the value cannot close the style tag it is written into.
 */
const COLOUR = /^(#[0-9a-f]{3,8}|(oklch|rgb|hsl)a?\([0-9.,%\s/-]+\))$/i;

export function brandColour(value: string | undefined): string | undefined {
  const v = value?.trim();
  return v && COLOUR.test(v) ? v : undefined;
}

/** The style that overrides --primary in light and dark, or an empty string when no brand colour is set. */
export function brandStyle(env: { light?: string; dark?: string }): string {
  const light = brandColour(env.light);
  const dark = brandColour(env.dark) ?? light;
  return [light && `:root{--primary:${light}}`, dark && `.dark{--primary:${dark}}`].filter(Boolean).join('');
}
