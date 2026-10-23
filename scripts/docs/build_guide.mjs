#!/usr/bin/env node
// Builds the client guide from its one source, the Markdown in docs/guide/:
//   docs/deploy/client-install-guide.html  one self-contained page (contents rail, light and dark, status badges, copy
//                                          buttons, Mermaid pre-rendered to inline SVG that follows the page theme);
//   docs/deploy/install-guide.md           shipped in the release package as INSTALL.md: the install and operate
//                                          sections, written only once the install section is no longer a placeholder.
// Usage: node scripts/docs/build_guide.mjs [--check]
//   --check  writes nothing; exits 1 when either output differs from what the build would write.
//
// Markdown conventions, each of which still reads plainly on GitHub and on the docs site:
//   docs/guide/README.md     the index: title, lede, an "At a glance" table (its State cells become the pills under the
//                            title) and a numbered list of links that sets the order of the sections.
//   ```mermaid               a diagram; an italic paragraph right after it is its caption.
//   > [!NOTE] / [!WARNING]   a note box.
//   <!-- site: cards -->     the table or list after it is drawn as cards (the docs site reads the same marker).
//   <!-- diagram: <name> --> the Mermaid block after it is replaced by docs/diagrams/<name>.svg once git tracks that file
//                            (diagrams drawn from the docs' data files); until then the Mermaid is rendered.
//   ![alt](file.svg)         a local image is inlined (SVG) or embedded (PNG, JPEG), so the page stays one file.
//   <!-- site: steps -->     the numbered list after it is drawn as steps.
//   <!-- guide: placeholder -->  the section is a placeholder; INSTALL.md is not written while install.md holds it.
//   <!-- guide: include from "## A" until "## B" --> followed by a paragraph linking another doc: the build shows that
//                            doc's part between the two headings in place of the link (readSection).
//   A table cell that is, or starts with, built, partial, planned or in progress is drawn with a status badge.
//   Links to another guide file become links inside the page; links to other docs go to the public repository.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, normalize, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Lexer, Marked } from 'marked';
import { renderMermaid } from './mermaid_svg.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const GUIDE = join(ROOT, 'docs/guide');
const HTML_OUT = join(ROOT, 'docs/deploy/client-install-guide.html');
const INSTALL_OUT = join(ROOT, 'docs/deploy/install-guide.md');
const REPO_URL = 'https://github.com/chanl-ai/ops-ai/blob/main/';
const INSTALL_SECTIONS = ['install.md', 'operate.md'];
const STATUS = [
  ['In progress', 'part'],
  ['Partial', 'part'],
  ['Planned', 'plan'],
  ['Built', 'ok'],
];
const CHECK = process.argv.includes('--check');

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const slug = (s) =>
  s
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .trim()
    .replace(/\s+/g, '-');
const read = (p) => readFileSync(p, 'utf8');

// ---------- the index ----------

function readIndex() {
  const text = read(join(GUIDE, 'README.md'));
  const title = text.match(/^# (.+)$/m)?.[1] ?? 'Ops AI guide';
  const body = text.replace(/^# .+\n/, '').replace(/^Status:.*\n(?:\S.*\n)*/m, '');
  const lede = body
    .split(/\n## /)[0]
    .trim()
    .split(/\n\n/)
    .filter((p) => p && !p.startsWith('|') && !p.startsWith('<!--'));
  const glance = [];
  const glanceBlock = body.match(/## At a glance\n\n((?:\|.*\n)+)/);
  if (glanceBlock) {
    for (const row of glanceBlock[1].trim().split('\n').slice(2)) {
      const [state, what] = row.split('|').slice(1, -1).map((c) => c.trim());
      glance.push({ state, what });
    }
  }
  const sections = [];
  for (const m of body.matchAll(/^\d+\. \[([^\]]+)\]\(([a-z0-9-]+\.md)\)/gm)) sections.push({ title: m[1], file: m[2], id: m[2].replace(/\.md$/, '') });
  if (sections.length === 0) throw new Error('docs/guide/README.md lists no sections ("1. [Title](file.md)")');
  return { title, lede, glance, sections };
}

// ---------- Markdown to HTML ----------

function statusBadge(text) {
  for (const [word, cls] of STATUS) {
    const m = text.match(new RegExp(`^${word}(?:[.:,;]?\\s+([\\s\\S]*))?$`, 'i'));
    if (m) return { badge: `<span class="b b-${cls}">${word}</span>`, rest: m[1] ?? '' };
  }
  return null;
}

function makeRenderer(ctx) {
  const marked = new Marked({ gfm: true });
  marked.use({
    renderer: {
      heading({ tokens, depth }) {
        const text = this.parser.parseInline(tokens);
        const id = `${ctx.section}-${slug(text)}`;
        const level = Math.min(depth + 1, 6);
        return `<h${level} id="${id}">${text}</h${level}>\n`;
      },
      link({ href, title, tokens }) {
        const text = this.parser.parseInline(tokens);
        return `<a href="${esc(ctx.href(href))}"${title ? ` title="${esc(title)}"` : ''}>${text}</a>`;
      },
      image({ href, text }) {
        if (/^https?:/.test(href)) return `<img alt="${esc(text)}" src="${esc(href)}">`;
        const path = normalize(join(GUIDE, href));
        if (!existsSync(path)) throw new Error(`docs/guide/${ctx.section}.md: image ${href} does not exist`);
        return imageHtml(path, text);
      },
      code({ text, lang }) {
        if (lang === 'mermaid') throw new Error('mermaid blocks are rendered by the section walk');
        return `<div class="cmd"><pre><code>${esc(text)}</code></pre></div>\n`;
      },
      table(token) {
        const cell = (c, tag) => {
          let inner = this.parser.parseInline(c.tokens);
          if (tag === 'td') {
            const s = statusBadge(c.text);
            if (s) inner = s.badge + (s.rest ? ` ${this.parser.parseInline(Lexer.lexInline(s.rest))}` : '');
          }
          return `<${tag}>${inner}</${tag}>`;
        };
        const head = `<tr>${token.header.map((c) => cell(c, 'th')).join('')}</tr>`;
        const rows = token.rows.map((r) => `<tr>${r.map((c) => cell(c, 'td')).join('')}</tr>`).join('\n');
        return `<div class="table-wrap"><table>\n<thead>${head}</thead>\n<tbody>\n${rows}\n</tbody></table></div>\n`;
      },
      blockquote({ tokens }) {
        const first = tokens[0];
        const alert = first?.type === 'paragraph' && first.text.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n?/);
        if (!alert) return `<blockquote>${this.parser.parse(tokens)}</blockquote>\n`;
        const kind = { NOTE: 'info', TIP: 'ok', IMPORTANT: 'info', WARNING: 'warn', CAUTION: 'warn' }[alert[1]];
        const rest = new Marked({ gfm: true }).lexer(first.raw.replace(/^\[![A-Z]+\]\s*\n?/, ''));
        const body = this.parser.parse([...rest, ...tokens.slice(1)]);
        return `<div class="note ${kind}">${body}</div>\n`;
      },
      strong({ tokens, text }) {
        const s = statusBadge(text);
        return s && !s.rest ? s.badge : `<strong>${this.parser.parseInline(tokens)}</strong>`;
      },
      html({ text }) {
        return /^\s*<!--/.test(text) ? '' : text;
      },
    },
  });
  return marked;
}

function cardsFromTable(token, marked) {
  const inline = (c) => marked.parseInline(c.text);
  const cards = token.rows.map((r) => {
    const s = statusBadge(r[r.length - 1].text);
    const lines = r.slice(1, s ? -1 : undefined).map((c, i) => `<p><span class="k">${esc(token.header[i + 1].text)}</span> ${inline(c)}</p>`);
    return `<div class="card"><h4>${inline(r[0])}${s ? ` ${s.badge}` : ''}</h4>${lines.join('')}${s?.rest ? `<p>${marked.parseInline(s.rest)}</p>` : ''}</div>`;
  });
  return `<div class="cards">${cards.join('\n')}</div>\n`;
}

/** A list under the cards marker: each item's leading bold text (or text before a colon) is the card's title. */
function cardsFromList(token, marked) {
  const cards = token.items.map((item) => {
    const m = item.text.match(/^\*\*(.+?)\*\*[:.]?\s*([\s\S]*)$/) ?? item.text.match(/^([^:]{1,60}):\s+([\s\S]*)$/);
    const [title, body] = m ? [m[1], m[2]] : [item.text, ''];
    const s = statusBadge(body);
    return `<div class="card"><h4>${marked.parseInline(title)}${s ? ` ${s.badge}` : ''}</h4>${(s ? s.rest : body) ? `<p>${marked.parseInline(s ? s.rest : body)}</p>` : ''}</div>`;
  });
  return `<div class="cards">${cards.join('\n')}</div>\n`;
}

/** A tracked export is read as HEAD holds it, so another builder's uncommitted edit never reaches the page. */
function svgSource(src) {
  const rel = relative(ROOT, src);
  return tracked(src) ? execFileSync('git', ['show', `HEAD:${rel}`], { cwd: ROOT, encoding: 'utf8' }) : read(src);
}

/** Inlines a local SVG (or embeds a PNG or JPEG as a data URI) so the page stays one file. */
function imageHtml(src, alt) {
  if (src.endsWith('.svg')) {
    const svg = svgSource(src).replace(/<\?xml[^>]*>\s*/, '');
    return /^<svg[^>]*\baria-label=/.test(svg) ? svg : svg.replace(/<svg\b/, `<svg role="img" aria-label="${esc(alt)}"`);
  }
  const type = src.endsWith('.png') ? 'image/png' : 'image/jpeg';
  return `<img alt="${esc(alt)}" src="data:${type};base64,${readFileSync(src).toString('base64')}">`;
}

/** Converts one section file's Markdown; mermaid blocks become placeholders filled after rendering. */
function sectionHtml(file, ctx, diagrams) {
  const marked = makeRenderer(ctx);
  const text = readSection(file)
    .replace(/^# .+\n/, '')
    .replace(/^Status:.*\n(?:\S.*\n)*/m, '');
  const tokens = marked.lexer(text);
  const out = [];
  let marker = null;
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.type === 'space') continue;
    if (t.type === 'html' && /<!--\s*site:\s*(\w+)\s*-->/.test(t.text)) {
      marker = t.text.match(/site:\s*(\w+)/)[1];
      continue;
    }
    if (t.type === 'html' && /<!--\s*diagram:\s*([a-z0-9-]+)\s*-->/.test(t.text)) {
      marker = `diagram:${t.text.match(/diagram:\s*([a-z0-9-]+)/)[1]}`;
      continue;
    }
    if (t.type === 'code' && t.lang === 'mermaid') {
      const id = `fig-${ctx.section}-${diagrams.filter((d) => d.section === ctx.section).length + 1}`;
      // A diagram drawn from the docs' data files replaces the Mermaid once it is exported to docs/diagrams/.
      const exported = marker?.startsWith('diagram:') ? join(ROOT, 'docs/diagrams', `${marker.slice(8)}.svg`) : null;
      if (exported && tracked(exported)) diagrams.push({ id, svg: imageHtml(exported, marker.slice(8)), section: ctx.section });
      else diagrams.push({ id, code: t.text, section: ctx.section });
      let j = i + 1;
      while (tokens[j]?.type === 'space') j++;
      const cap = tokens[j];
      let caption = '';
      if (cap?.type === 'paragraph' && /^\*[^*][\s\S]*\*$/.test(cap.text.trim())) {
        caption = `<figcaption>${marked.parseInline(cap.text.trim().slice(1, -1))}</figcaption>`;
        i = j;
      }
      out.push(`<figure id="${id}">@@${id}@@${caption}</figure>\n`);
      marker = null;
      continue;
    }
    if (marker === 'cards' && t.type === 'table') out.push(cardsFromTable(t, marked));
    else if (marker === 'cards' && t.type === 'list') out.push(cardsFromList(t, marked));
    else if (marker === 'steps' && t.type === 'list' && t.ordered) out.push(marked.parser([t]).replace(/^<ol([^>]*)>/, '<ol class="steps"$1>'));
    else out.push(marked.parser([t]));
    marker = null;
  }
  return out.join('');
}

/** Whether git tracks the file: an untracked export is another builder's work in progress, and the committed page must
 *  equal what HEAD builds. */
function tracked(path) {
  try {
    execFileSync('git', ['ls-files', '--error-unmatch', relative(ROOT, path)], { cwd: ROOT, stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

// ---------- includes ----------

/**
 * A section file with its includes expanded. The directive is a comment followed by one paragraph holding a link to
 * another doc, so GitHub shows the link and the build shows the doc:
 *   <!-- guide: include from "## Heading" until "## Heading" -->
 *   The steps are in [the install guide](../deploy/install.md).
 * Both bounds are optional; the included part keeps its headings, and its relative links are rewritten to resolve from
 * docs/guide/. Including keeps one source: the other doc is never copied into the guide.
 */
function readSection(file) {
  return read(join(GUIDE, file)).replace(
    /<!--\s*guide:\s*include((?:\s+(?:from|until)\s+"[^"]+")*)\s*-->\n+[^\n]*\]\(([^)#]+\.md)\)[^\n]*\n/g,
    (_m, bounds, href) => {
      const target = normalize(join(GUIDE, href));
      if (!existsSync(target)) throw new Error(`docs/guide/${file}: include ${href} does not exist`);
      let body = read(target);
      const from = bounds.match(/from\s+"([^"]+)"/)?.[1];
      const until = bounds.match(/until\s+"([^"]+)"/)?.[1];
      if (from) {
        const i = body.indexOf(`\n${from}\n`);
        if (i < 0) throw new Error(`docs/guide/${file}: ${href} has no heading "${from}"`);
        body = body.slice(i + 1);
      }
      if (until) {
        const i = body.indexOf(`\n${until}\n`);
        if (i < 0) throw new Error(`docs/guide/${file}: ${href} has no heading "${until}"`);
        body = body.slice(0, i + 1);
      }
      const dir = dirname(target);
      body = body.replace(/\]\((?!https?:|mailto:|#)([^)#]+)(#[^)]*)?\)/g, (_l, p, a = '') => `](${relative(GUIDE, join(dir, p))}${a})`);
      return `${body.trim()}\n`;
    },
  );
}

// ---------- links ----------

function hrefFor(file, sectionIds) {
  return (href) => {
    if (/^(https?:|mailto:)/.test(href)) return href;
    if (href.startsWith('#')) return `#${file.replace(/\.md$/, '')}-${href.slice(1)}`;
    const [path, anchor] = href.split('#');
    const target = normalize(join('docs/guide', path));
    const guideFile = relative('docs/guide', target);
    if (!guideFile.includes('/') && sectionIds.has(guideFile.replace(/\.md$/, ''))) {
      const id = guideFile.replace(/\.md$/, '');
      return anchor ? `#${id}-${anchor}` : `#${id}`;
    }
    if (!existsSync(join(ROOT, target))) throw new Error(`docs/guide/${file}: link ${href} points at ${target}, which does not exist`);
    return REPO_URL + target + (anchor ? `#${anchor}` : '');
  };
}

// ---------- INSTALL.md ----------

function installMarkdown(index) {
  const parts = INSTALL_SECTIONS.map((f) => ({ f, text: readSection(f) }));
  if (parts.some((p) => p.text.includes('<!-- guide: placeholder -->'))) return null;
  const ids = new Set(index.sections.map((s) => s.id));
  const body = parts
    .map(({ f, text }) =>
      text
        .replace(/^Status:.*\n(?:\S.*\n)*\n?/m, '')
        .replace(/^(#+) /gm, '#$1 ')
        // Links to sections outside INSTALL.md go to the public repository, since the package holds no docs folder.
        .replace(/\]\((?!https?:|mailto:|#)([^)#]+)(#[^)]*)?\)/g, (_m, p, a = '') => {
          const target = normalize(join('docs/guide', p));
          const id = relative('docs/guide', target).replace(/\.md$/, '');
          if (INSTALL_SECTIONS.includes(`${id}.md`)) return `](${a || `#${id}`})`;
          return `](${REPO_URL}${ids.has(id) ? `docs/guide/${id}.md` : target}${a})`;
        }),
    )
    .join('\n');
  // The first lines are what a client team reads first, so they hold no paths; the edit note is a comment.
  return `# Install and operate Ops AI\n\nStatus: current. How to install, run and maintain Ops AI on your own machines. The full client guide adds the architecture, data, security and deployment options.\n\n<!-- Generated from docs/guide/install.md and docs/guide/operate.md by scripts/docs/build_guide.mjs; edit those, then run the build. The full guide is docs/deploy/client-install-guide.html. -->\n\n${body.trim()}\n`;
}

// ---------- the page ----------

const LOGO = `<svg class="brand-mark" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><g transform="rotate(-90 12 12)"><path d="M5.636 5.636a9 9 0 1 0 12.728 12.728a9 9 0 0 0 -12.728 -12.728z"/><path d="M16.243 7.757a6 6 0 0 0 -8.486 0"/></g></svg>`;

function page(index, sections) {
  const css = read(join(dirname(fileURLToPath(import.meta.url)), 'guide.css'));
  const pills = index.glance
    .map(({ state, what }) => {
      const s = statusBadge(state);
      const cls = s ? s.badge.match(/b-(\w+)/)[1] : 'plan';
      return `<span class="pill ${cls}">${new Marked().parseInline(what)}</span>`;
    })
    .join('\n    ');
  const toc = index.sections.map((s, i) => `<li><a href="#${s.id}"><span class="n">${i + 1}</span>${esc(s.title)}</a></li>`).join('\n      ');
  const body = sections
    .map((s, i) => `<section id="${s.id}" aria-labelledby="${s.id}-h">\n<h2 id="${s.id}-h"><span class="n">${i + 1}</span>${esc(s.title)}</h2>\n${s.html}</section>`)
    .join('\n\n');
  const ledeMarked = makeRenderer({ section: 'intro', href: (h) => h });
  const lede = index.lede.map((p) => `<p class="lede">${ledeMarked.parseInline(p)}</p>`).join('\n  ');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Ops AI Install Guide</title>
<meta name="description" content="What Ops AI is, how its parts fit together, where its data lives, how it is secured, and how a client team installs and runs it.">
<!-- Generated by scripts/docs/build_guide.mjs from docs/guide/*.md; edit the Markdown and run the build. -->
<style>
${css}</style>
</head>
<body>
<header class="masthead">
  <a class="brand" href="https://chanl.ai">${LOGO}<span><b>Ops AI</b> by Chanl AI · Architecture and install guide</span></a>
  <h1>${esc(index.title)}</h1>
  ${lede}
  <div class="status-strip" aria-label="At a glance">
    ${pills}
  </div>
</header>

<div class="page">
  <nav class="toc" aria-label="Contents">
    <h2>Contents</h2>
    <ol>
      ${toc}
    </ol>
  </nav>

  <main>
${body}
  </main>
</div>

<footer>Ops AI by Chanl AI, <a href="https://chanl.ai">chanl.ai</a>. This page is generated from the Markdown in <a href="${REPO_URL}docs/guide/README.md"><code>docs/guide/</code></a> of the Ops AI repository; the install and operate sections also ship in the release package as <code>INSTALL.md</code>.</footer>

<script>
// A copy button on each command block; when the clipboard is refused, the command is selected for a manual copy.
document.querySelectorAll('.cmd').forEach((box, i) => {
  const code = box.querySelector('code');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'copy';
  button.id = 'copy-' + i;
  button.textContent = 'Copy';
  button.setAttribute('aria-label', 'Copy command');
  button.addEventListener('click', () => {
    const select = () => { const r = document.createRange(); r.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
    const done = (label) => { button.textContent = label; setTimeout(() => { button.textContent = 'Copy'; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code.innerText).then(() => done('Copied'), () => { select(); done('Selected'); });
    } else { select(); done('Selected'); }
  });
  box.appendChild(button);
});
</script>
</body>
</html>
`;
}

// ---------- main ----------

async function main() {
  const index = readIndex();
  const ids = new Set(index.sections.map((s) => s.id));
  const diagrams = [];
  const sections = index.sections.map((s) => {
    if (!existsSync(join(GUIDE, s.file))) throw new Error(`docs/guide/README.md lists ${s.file}, which does not exist`);
    return { ...s, html: sectionHtml(s.file, { section: s.id, href: hrefFor(s.file, ids) }, diagrams) };
  });
  const svgs = await renderMermaid(diagrams.filter((d) => d.code));
  for (const d of diagrams) if (d.svg) svgs.set(d.id, d.svg);
  for (const s of sections) s.html = s.html.replace(/@@(fig-[a-z0-9-]+)@@/g, (_m, id) => svgs.get(id));
  const outputs = [[HTML_OUT, page(index, sections)]];
  const install = installMarkdown(index);
  if (install) outputs.push([INSTALL_OUT, install]);
  else console.log('build_guide: install.md is a placeholder, so INSTALL.md (docs/deploy/install-guide.md) is left as it is');

  let stale = 0;
  for (const [path, content] of outputs) {
    const rel = relative(ROOT, path);
    if (CHECK) {
      const same = existsSync(path) && read(path) === content;
      if (!same) {
        stale++;
        console.error(`build_guide: ${rel} differs from what docs/guide/ builds; run node scripts/docs/build_guide.mjs`);
      }
    } else {
      writeFileSync(path, content);
      console.log(`build_guide: wrote ${rel} (${content.length} bytes, ${diagrams.length} diagrams)`);
    }
  }
  if (CHECK && stale) process.exit(1);
  if (CHECK) console.log(`build_guide: ${outputs.length} output(s) match docs/guide/ (${index.sections.length} sections, ${diagrams.length} diagrams)`);
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
