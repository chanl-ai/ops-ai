// Renders Mermaid diagrams to inline SVG in headless Chromium (the use case harness's), themed with sentinel colours that
// are then replaced by the page's CSS variables, so one SVG follows the page into light and dark mode. Mermaid derives
// some colours from the ones it is given (lighter fills, borders), so every colour the theme sets is a sentinel and any
// colour left over after the swap fails the build: a hard-coded hex would show light-mode colours in dark mode.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from '@ops-ai/usecase-runner/harness';

const require = createRequire(import.meta.url);

// Sentinel hex → page token. Sentinels are colours no diagram would choose; each maps to one token.
export const SENTINELS = {
  '#010101': 'var(--text)',
  '#020202': 'var(--surface)',
  '#030303': 'var(--border-strong)',
  '#040404': 'var(--muted)',
  '#050505': 'var(--sunk)',
  '#060606': 'var(--accent)',
  '#070707': 'var(--accent-soft)',
  '#080808': 'var(--bg)',
  '#090909': 'var(--line)',
};

// Status classes a diagram may use with `class X built` (or `:::built`); each is drawn from the page's badge tokens.
const STATUS_CLASSES = [
  'classDef built fill:#0a0a01,stroke:#0a0a02,color:#010101',
  'classDef partial fill:#0a0a03,stroke:#0a0a04,color:#010101',
  'classDef planned fill:#0a0a05,stroke:#0a0a06,color:#010101,stroke-dasharray:5 3',
  'classDef store fill:#0a0a07,stroke:#0a0a08,color:#010101',
  'classDef outside fill:#050505,stroke:#040404,color:#010101,stroke-dasharray:2 3',
];
Object.assign(SENTINELS, {
  '#0a0a01': 'var(--ok-soft)',
  '#0a0a02': 'var(--ok)',
  '#0a0a03': 'var(--warn-soft)',
  '#0a0a04': 'var(--warn)',
  '#0a0a05': 'var(--plan-soft)',
  '#0a0a06': 'var(--plan)',
  '#0a0a07': 'var(--store-soft)',
  '#0a0a08': 'var(--store)',
});

const FIXED = [
  ['flood-color="#(?:000000|ffffff)"', 'flood-color="var(--text)"'],
  ['drop-shadow\\(\\s*1px 2px 2px rgba\\(185,\\s*185,\\s*185,\\s*1\\)\\)', 'none'],
  ['#fdfdfd\\b', 'var(--muted)'],
  ['"#eaeaea"', '"var(--surface)"'],
  ['"#EDF2AE"', '"var(--accent-soft)"'],
  ['"#666"', '"var(--border-strong)"'],
  ['"#999"', '"var(--line)"'],
  ['#e0e0e0\\b', 'var(--sunk)'],
  ['rgba\\(0,\\s*0,\\s*0,\\s*0\\.2\\)', 'color-mix(in srgb, var(--text) 20%, transparent)'],
  ['rgb\\(0 0 0 / 0\\.4\\)', 'color-mix(in srgb, var(--text) 40%, transparent)'],
];

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

const THEME = {
  fontFamily: FONT,
  fontSize: '14px',
  background: '#020202',
  primaryColor: '#020202',
  primaryTextColor: '#010101',
  primaryBorderColor: '#030303',
  secondaryColor: '#050505',
  secondaryTextColor: '#010101',
  secondaryBorderColor: '#030303',
  tertiaryColor: '#050505',
  tertiaryTextColor: '#010101',
  tertiaryBorderColor: '#030303',
  mainBkg: '#020202',
  nodeBorder: '#030303',
  nodeTextColor: '#010101',
  textColor: '#010101',
  titleColor: '#010101',
  lineColor: '#040404',
  defaultLinkColor: '#040404',
  clusterBkg: '#080808',
  clusterBorder: '#090909',
  edgeLabelBackground: '#020202',
  labelBackground: '#020202',
  noteBkgColor: '#070707',
  noteTextColor: '#010101',
  noteBorderColor: '#060606',
  actorBkg: '#020202',
  actorBorder: '#030303',
  actorTextColor: '#010101',
  actorLineColor: '#090909',
  signalColor: '#040404',
  signalTextColor: '#010101',
  labelBoxBkgColor: '#050505',
  labelBoxBorderColor: '#030303',
  labelTextColor: '#010101',
  loopTextColor: '#010101',
  activationBkgColor: '#050505',
  activationBorderColor: '#030303',
  sequenceNumberColor: '#020202',
  attributeBackgroundColorOdd: '#020202',
  attributeBackgroundColorEven: '#050505',
  relationColor: '#040404',
  relationLabelColor: '#010101',
  relationLabelBackground: '#020202',
  altBackground: '#050505',
  errorBkgColor: '#070707',
  errorTextColor: '#010101',
};

/** Adds the status classes to a flowchart that uses them; other diagram kinds get the source unchanged. */
function withStatusClasses(code) {
  const kind = code.trimStart().split(/\s/, 1)[0];
  if (!/^(flowchart|graph)$/.test(kind)) return code;
  return `${code.trimEnd()}\n${STATUS_CLASSES.join('\n')}\n`;
}

/** The colours left in an SVG after the swap: anything here would not follow the theme. */
export function strayColours(svg) {
  const found = new Set();
  for (const m of svg.matchAll(/#[0-9a-fA-F]{3,8}\b(?![\w-])/g)) found.add(m[0]);
  for (const m of svg.matchAll(/\b(?:rgba?|hsla?)\([^)]*\)/g)) found.add(m[0]);
  // Ids in url(#…) and href="#…" are references, not colours.
  for (const m of svg.matchAll(/(?:url\(|href=")#([0-9a-fA-F]{3,8})\b/g)) found.delete(`#${m[1]}`);
  return [...found];
}

function swap(svg) {
  let out = svg;
  for (const [hex, token] of Object.entries(SENTINELS)) {
    out = out.replaceAll(new RegExp(hex, 'gi'), token);
    // The browser reports a computed colour as rgb() or rgba(); a sentinel can come back in either form.
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    out = out.replace(new RegExp(`rgb\\(\\s*${r},\\s*${g},\\s*${b}\\s*\\)`, 'g'), token);
    out = out.replace(new RegExp(`rgba\\(\\s*${r},\\s*${g},\\s*${b},\\s*([0-9.]+)\\s*\\)`, 'g'), (_m, a) =>
      Number(a) >= 1 ? token : `color-mix(in srgb, ${token} ${Math.round(Number(a) * 100)}%, transparent)`);
  }
  // Mermaid's own fallbacks that do not come from the theme: markers and edge labels drawn in black or white.
  out = out
    .replace(/fill:\s*(?:#000000|#000|black)\b/gi, 'fill:var(--muted)')
    .replace(/stroke:\s*(?:#000000|#000|black)\b/gi, 'stroke:var(--muted)')
    .replace(/fill="(?:#000000|#000|black)"/gi, 'fill="var(--muted)"')
    .replace(/stroke="(?:#000000|#000|black)"/gi, 'stroke="var(--muted)"')
    .replace(/fill:\s*(?:#ffffff|#fff|white)\b/gi, 'fill:var(--surface)')
    .replace(/fill="(?:#ffffff|#fff|white)"/gi, 'fill="var(--surface)"')
    .replace(/rgba\(232,\s*232,\s*232,\s*0\.8\)/g, 'var(--surface)');
  // Colours Mermaid writes as presentation attributes or fixed defaults; the theme's CSS wins over most of them, and
  // each is mapped anyway so no light-mode value survives in dark mode.
  for (const [raw, token] of FIXED) out = out.replace(new RegExp(raw, 'gi'), token);
  // ER attribute rows get greys Mermaid derives from the sentinels with hsl(); light ones become the surface, dark the sunk tone.
  out = out.replace(/hsl\(0,\s*0%,\s*([0-9.]+)%\)/g, (_m, l) => (Number(l) >= 50 ? 'var(--surface)' : 'var(--sunk)'));
  return out;
}

/**
 * Renders each diagram in one browser session. `diagrams` is [{ id, code }]; returns Map(id → svg).
 * Throws on a syntax error or a colour left over after the swap, naming the diagram.
 */
export async function renderMermaid(diagrams) {
  const out = new Map();
  if (diagrams.length === 0) return out;
  const bundle = readFileSync(require.resolve('mermaid/dist/mermaid.min.js'), 'utf8');
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
    await page.setContent(`<!doctype html><html><head><style>body{font-family:${FONT};font-size:14px}</style></head><body></body></html>`);
    await page.addScriptTag({ content: bundle });
    await page.evaluate((theme) => {
      // @ts-ignore: the bundle sets window.mermaid
      window.mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        themeVariables: theme,
        securityLevel: 'strict',
        htmlLabels: false,
        look: 'classic',
        flowchart: { htmlLabels: false, useMaxWidth: false, curve: 'basis', padding: 10, nodeSpacing: 22, rankSpacing: 40, wrappingWidth: 320, minNodeWidth: 40 },
        sequence: { look: 'classic', useMaxWidth: false, mirrorActors: false, actorMargin: 40, messageMargin: 30, wrap: true, width: 140 },
        er: { useMaxWidth: false, layoutDirection: 'TB' },
        state: { useMaxWidth: false },
      });
    }, THEME);
    for (const { id, code } of diagrams) {
      const svg = await page.evaluate(
        async ([domId, src]) => {
          // @ts-ignore
          const { svg } = await window.mermaid.render(domId, src);
          return svg;
        },
        [id, withStatusClasses(code)],
      ).catch((e) => {
        throw new Error(`mermaid: diagram ${id} does not render: ${e.message.split('\n')[0]}`);
      });
      const swapped = swap(svg);
      const stray = strayColours(swapped);
      if (stray.length) throw new Error(`mermaid: diagram ${id} keeps colours that do not follow the theme: ${stray.join(', ')}`);
      out.set(id, swapped);
    }
  } finally {
    await browser.close();
  }
  return out;
}
