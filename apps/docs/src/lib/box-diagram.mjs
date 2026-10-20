/**
 * Draws an architecture diagram (boxes in groups, stacked in bands, with orthogonal links) from a data file in
 * docs/diagrams/*.yaml, as an SVG string. The docs site renders it live (BoxDiagram) and
 * scripts/export-diagrams.mjs writes the same drawing to docs/diagrams/<name>.svg for GitHub.
 *
 * Data shape (see docs/diagrams/README.md):
 *   title, caption, width (default 980)
 *   bands: [{ groups: [group], gap }]              stacked top to bottom; groups sit side by side
 *   group: { id, label, note, style, span, columns, rows: [row] }
 *   row:   { boxes: [box] } | { chips: { label, items: [string] } } | { text: string }
 *   box:   { id, label, note, style, href, bold }
 *   links: [{ from, to, label, style, fromX, toX, straight }]  from/to: box, chip or group ids; fromX/toX: 0..1
 *          along the edge; straight: a plain vertical line into a lower target that spans the start
 * Styles: default, new (dashed green: to build), pack (purple), host (blue), port (soft), muted.
 */

const FONT = 'var(--ops-font, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif)';
const PAD = 16;
const GROUP_GAP = 60;
const BAND_GAP = 70;
const BOX_H = 36;
const BOX_NOTE_H = 46;
const ROW_GAP = 12;
const CHIP_H = 26;

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// Text widths are estimated, not measured: the drawing must come out the same in node and in the browser.
const textWidth = (s, size = 13, bold = false) => String(s ?? '').length * size * (bold ? 0.58 : 0.54);

function layoutRow(row, x, y, w, columns, items) {
  if (row.text) {
    items.push({ kind: 'text', x, y: y + 12, text: row.text });
    return 6;
  }
  if (row.chips) {
    const labelW = row.chips.label ? textWidth(row.chips.label, 11.5) + 12 : 0;
    if (row.chips.label) items.push({ kind: 'text', x, y: y + 17, text: row.chips.label });
    const chips = row.chips.items.map((item) => (typeof item === 'string' ? { label: item } : item));
    const natural = chips.map((c) => Math.max(48, textWidth(c.label, 11.5) + 18));
    // Chips keep their natural width unless the row is too narrow for them, then they shrink to fit it.
    const room = w - labelW - 6 * (chips.length - 1);
    const scale = Math.min(1, room / natural.reduce((a, n) => a + n, 0));
    let cx = x + labelW;
    chips.forEach((c, i) => {
      const cw = natural[i] * scale;
      items.push({ kind: 'chip', id: c.id, x: cx, y, w: cw, h: CHIP_H, label: c.label, style: row.chips.style ?? 'pack' });
      cx += cw + 6;
    });
    return CHIP_H;
  }
  const boxes = row.boxes ?? [];
  const hasNote = boxes.some((b) => b.note);
  const h = hasNote ? BOX_NOTE_H : BOX_H;
  const gap = 10;
  if (columns) {
    const bw = (w - gap * (columns - 1)) / columns;
    boxes.forEach((b, i) => items.push({ kind: 'box', ...b, x: x + i * (bw + gap), y, w: bw, h, left: true }));
    return h;
  }
  // Widths follow the labels, then stretch to fill the row.
  const natural = boxes.map((b) => Math.max(72, textWidth(b.label, 13, b.bold) + 28));
  const scale = (w - gap * (boxes.length - 1)) / natural.reduce((a, n) => a + n, 0);
  let bx = x;
  boxes.forEach((b, i) => {
    const bw = natural[i] * scale;
    items.push({ kind: 'box', ...b, x: bx, y, w: bw, h, left: Boolean(b.note) });
    bx += bw + gap;
  });
  return h;
}

function layout(data) {
  const width = data.width ?? 980;
  const items = [];
  const byId = {};
  let y = 20;
  for (const band of data.bands) {
    const groups = band.groups;
    const spans = groups.map((g) => g.span ?? 1);
    const total = spans.reduce((a, n) => a + n, 0);
    const avail = width - 40 - GROUP_GAP * (groups.length - 1);
    let gx = 20;
    let bandH = 0;
    const placed = [];
    for (const [i, g] of groups.entries()) {
      const gw = (avail * spans[i]) / total;
      let inner = y + (g.label ? 26 : PAD);
      const headerItems = [];
      if (g.label) headerItems.push({ kind: 'title', x: gx + PAD, y: y + 26, text: g.label });
      if (g.note) {
        inner += 18;
        headerItems.push({ kind: 'text', x: gx + PAD, y: y + 44, text: g.note });
      }
      inner += 14;
      const rowItems = [];
      for (const row of g.rows ?? []) {
        if (row.boxes && g.columns && row.boxes.length > g.columns) {
          for (let k = 0; k < row.boxes.length; k += g.columns) {
            inner += layoutRow({ boxes: row.boxes.slice(k, k + g.columns) }, gx + PAD, inner, gw - 2 * PAD, g.columns, rowItems) + ROW_GAP / 1.5;
          }
          continue;
        }
        inner += layoutRow(row, gx + PAD, inner, gw - 2 * PAD, g.columns, rowItems) + ROW_GAP;
      }
      const gh = inner - y + 4;
      placed.push({ g, gx, gw, items: [...headerItems, ...rowItems] });
      bandH = Math.max(bandH, gh);
      gx += gw + GROUP_GAP;
    }
    for (const p of placed) {
      const groupItem = { kind: 'group', id: p.g.id, x: p.gx, y, w: p.gw, h: bandH, style: p.g.style, href: p.g.href };
      items.push(groupItem, ...p.items);
    }
    y += bandH + (band.gap ?? BAND_GAP);
  }
  for (const it of items) if (it.id) byId[it.id] = it;
  const height = y - (data.bands.at(-1)?.gap ?? BAND_GAP) + 20;
  return { width, height, items, byId };
}

function routeLinks(data, byId, items) {
  const groups = items.filter((i) => i.kind === 'group');
  const groupOf = (it) => groups.find((g) => it.x >= g.x && it.x <= g.x + g.w && it.y >= g.y && it.y <= g.y + g.h) ?? it;
  const lanes = new Map(); // band bottom -> lanes used in the gap below it
  return (data.links ?? []).map((link) => {
    const a = byId[link.from];
    const b = byId[link.to];
    if (!a || !b) throw new Error(`diagram link ${link.from} -> ${link.to}: unknown id`);
    const ax = a.x + a.w * (link.fromX ?? 0.5);
    const bx = b.x + b.w * (link.toX ?? 0.5);
    const below = b.y > a.y + a.h;
    let d;
    let labelAt;
    if (below && (Math.abs(ax - bx) < 2 || (link.straight && ax >= b.x && ax <= b.x + b.w))) {
      d = `M${ax},${a.y + a.h} L${ax},${b.y - 4}`;
      labelAt = { x: ax + 6, y: (a.y + a.h + b.y) / 2 + 4 };
    } else {
      // Out of the bottom of the source, along a lane in the gap under its band, then into the target: from above
      // when the target sits lower, from below when it sits in the same band.
      const g = groupOf(a);
      const floor = g.y + g.h;
      const used = lanes.get(floor) ?? 0;
      lanes.set(floor, used + 1);
      const lane = floor + 20 + used * 20;
      const by = b.y > lane ? b.y - 4 : b.y + b.h + 4;
      d = `M${ax},${a.y + a.h} L${ax},${lane} L${bx},${lane} L${bx},${by}`;
      labelAt = { x: Math.min(ax, bx) + 30, y: lane - 6 };
    }
    return { d, dashed: link.style === 'dashed', label: link.label, labelAt };
  });
}

/**
 * @param {object} data the parsed YAML
 * @param {{ standalone?: boolean, linkHref?: (href: string) => string }} [opts] standalone: embed the light and
 *   dark palette (for an SVG file); linkHref: make boxes with an href into links (the live diagram)
 */
export function renderBoxDiagram(data, opts = {}) {
  const { width, height, items, byId } = layout(data);
  const links = routeLinks(data, byId, items);
  const parts = [];
  const cls = (base, style) => (style && style !== 'default' ? `${base} ${base}-${style}` : base);
  const wrap = (it, inner) =>
    it.href && opts.linkHref ? `<a href="${esc(opts.linkHref(it.href))}" class="lnk">${inner}</a>` : inner;
  for (const it of items) {
    if (it.kind === 'group') parts.push(wrap(it, `<rect class="${cls('grp', it.style)}" x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" rx="10"/>`));
    if (it.kind === 'title') parts.push(`<text class="tb" x="${it.x}" y="${it.y}">${esc(it.text)}</text>`);
    if (it.kind === 'text') parts.push(`<text class="ts" x="${it.x}" y="${it.y}">${esc(it.text)}</text>`);
    if (it.kind === 'chip') {
      parts.push(`<rect class="${cls('bx', it.style)}" x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" rx="6"/>`);
      parts.push(`<text class="ts" x="${it.x + it.w / 2}" y="${it.y + 17}" text-anchor="middle">${esc(it.label)}</text>`);
    }
    if (it.kind === 'box') {
      const r = `<rect class="${cls('bx', it.style)}" x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" rx="6"/>`;
      const t = it.note
        ? `<text class="tb" x="${it.x + 10}" y="${it.y + 20}">${esc(it.label)}</text><text class="ts" x="${it.x + 10}" y="${it.y + 37}">${esc(it.note)}</text>`
        : `<text class="${it.bold ? 'tb' : 't'}" x="${it.x + it.w / 2}" y="${it.y + 22}" text-anchor="middle">${esc(it.label)}</text>`;
      parts.push(wrap(it, r + t));
    }
  }
  for (const l of links) {
    parts.push(`<path class="ln" d="${l.d}"${l.dashed ? ' stroke-dasharray="5 3"' : ''} marker-end="url(#arrow)"/>`);
    if (l.label) parts.push(`<text class="lbl" x="${l.labelAt.x}" y="${l.labelAt.y}">${esc(l.label)}</text>`);
  }
  const style = opts.standalone ? `<style>${STANDALONE_CSS}</style>` : '';
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${esc(data.title)}" class="ops-box-diagram">` +
    `<title>${esc(data.title)}</title>${style}` +
    `<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>` +
    parts.join('') +
    `</svg>`
  );
}

/** The diagram palette. The site maps these variables to its theme (global.css); an exported SVG embeds both. */
export const DIAGRAM_CSS = `
.ops-box-diagram{font-family:${FONT};color:var(--d-fg)}
.ops-box-diagram .grp{fill:var(--d-card);stroke:var(--d-fg);stroke-width:1.2}
.ops-box-diagram .bx{fill:var(--d-card);stroke:var(--d-fg);stroke-width:1.2}
.ops-box-diagram .bx-port{fill:var(--d-soft);stroke:var(--d-fg);stroke-width:1}
.ops-box-diagram .grp-new,.ops-box-diagram .bx-new{fill:var(--d-new-soft);stroke:var(--d-new);stroke-width:1.4;stroke-dasharray:5 3}
.ops-box-diagram .bx-pack{fill:var(--d-pack-soft);stroke:var(--d-pack);stroke-width:1.3}
.ops-box-diagram .grp-host,.ops-box-diagram .bx-host{fill:var(--d-host-soft);stroke:var(--d-host);stroke-width:1.3}
.ops-box-diagram .grp-muted,.ops-box-diagram .bx-muted{fill:var(--d-soft);stroke:var(--d-muted);stroke-width:1;stroke-dasharray:2 3}
.ops-box-diagram .ln{fill:none;stroke:var(--d-fg);stroke-width:1.3}
.ops-box-diagram .arrow{fill:var(--d-fg)}
.ops-box-diagram text{fill:var(--d-fg)}
.ops-box-diagram .t{font-size:13px}
.ops-box-diagram .tb{font-size:13px;font-weight:600}
.ops-box-diagram .ts{font-size:11.5px;fill:var(--d-muted)}
.ops-box-diagram .lbl{font-size:11.5px;fill:var(--d-accent)}
.ops-box-diagram .lnk:hover rect{stroke:var(--d-accent);stroke-width:2}
`;

const LIGHT = '--d-fg:#1d1f22;--d-muted:#5d636b;--d-card:#ffffff;--d-soft:#f1f2f3;--d-accent:#2f5bd3;--d-new:#0f7a55;--d-new-soft:#e3f4ec;--d-pack:#5b3fd1;--d-pack-soft:#efeafc;--d-host:#1a5fb4;--d-host-soft:#e4edf9';
const DARK = '--d-fg:#e6e8eb;--d-muted:#a0a6ae;--d-card:#1c1f23;--d-soft:#22262b;--d-accent:#8fb0ff;--d-new:#5fd3a5;--d-new-soft:#17332a;--d-pack:#b7a6ff;--d-pack-soft:#2a2347;--d-host:#8ab6f2;--d-host-soft:#1c2a40';
const STANDALONE_CSS = `svg{${LIGHT}}@media (prefers-color-scheme: dark){svg{${DARK}}}${DIAGRAM_CSS}`;
export const DIAGRAM_PALETTE = { light: LIGHT, dark: DARK };
