/**
 * Maps ops-ai's plain markdown onto the site's components at build time. The conventions are documented for authors
 * in docs/README.md ("How the docs site shows a page"); keep the two in step.
 *
 * - the first `# heading` becomes the page title
 * - a "Status: ..." first paragraph becomes the status line with a badge
 * - a table cell that starts with built, partial, planned or not built shows that word as a badge
 * - `<!-- site: cards -->` above a table or a list renders it as summary cards
 * - `<!-- site: steps -->` above a numbered list renders it as steps
 * - a GitHub alert (`> [!NOTE]`, `> [!WARNING]` ...) becomes a callout
 * - ```mermaid blocks render as diagrams that follow the light and dark theme
 * - an image of docs/diagrams/<name>.svg, where docs/diagrams/<name>.yaml exists, becomes the live diagram
 * - any other lone image becomes a framed figure with its alt text as the caption
 * - every relative link resolves to a page here, a standalone HTML page, or a file on GitHub; a code span that names
 *   a file in the repository becomes a link to it
 *
 * A link to a page or file that does not exist is an error. scripts/check-links.mjs runs this plugin over every page
 * before `next build`, because a throw inside the build surfaces only as an unreadable module error.
 */
import path from 'node:path';

import { toString as mdToString } from 'mdast-util-to-string';
import { SKIP, visit } from 'unist-util-visit';

import { githubUrl, isSitePage, repoIndex } from './repo.mjs';

const BADGE = /^(not built|built|partial|planned)(?=$|[\s,.;:)])[\s,.;:)-]*/i;
const STATUS_WORDS =
  /^(not built|not started|in progress|partly built|built|partial|planned|designed|proposed|proposal|done|passing|failing|retired|superseded|current|option|decided|draft|blocked|deferred|dropped|historical|approved|accepted|runs today|not yet runnable)\b[\s,.:;)-]*/i;
const CODE_PATH = /^(?:\.{0,2}\/)?[\w@.-]+(?:\/[\w@.-]+)*\/?(?::(\d+)(?:-(\d+))?)?$/;
const ALERTS = { NOTE: 'info', TIP: 'info', IMPORTANT: 'info', WARNING: 'warn', CAUTION: 'error' };

/** Where a repository path points on the site, or why it cannot. */
export function resolveRepoPath(repoPath, hash = '', line) {
  const idx = repoIndex();
  const p = repoPath.replace(/\/$/, '');
  const page = idx.pages[p] ?? idx.pages[`${p}/README.md`];
  if (page) {
    const anchor = decodeURIComponent(hash.slice(1));
    if (anchor && !page.anchors.includes(anchor)) return { broken: `no heading #${anchor} in ${p}` };
    return { url: page.url + hash };
  }
  if (p.startsWith('docs/') && p.endsWith('.html') && idx.files.has(p)) return { url: `/files/${p.slice(5)}${hash}` };
  if (idx.files.has(p)) return { url: githubUrl('blob', p, line ? `#L${line}` : hash) };
  if (idx.dirs.has(p)) return { url: githubUrl('tree', p) };
  return { broken: `${p} does not exist in the repository` };
}

function jsx(name, attributes, children = [], flow = true) {
  return {
    type: flow ? 'mdxJsxFlowElement' : 'mdxJsxTextElement',
    name,
    attributes: Object.entries(attributes)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => ({ type: 'mdxJsxAttribute', name: k, value: v })),
    children,
    data: { _mdxExplicitJsx: true },
  };
}

/** Splits a leading word matching `re` off the first text node of `children` and returns it, lower-cased. */
function takeWord(children, re) {
  const first = children[0];
  if (!first || first.type !== 'text') return undefined;
  const m = first.value.match(re);
  if (!m) return undefined;
  first.value = first.value.slice(m[0].length);
  if (!first.value) children.shift();
  return m[1].toLowerCase();
}

/** Links inside a card would nest inside the card's own link, which is invalid HTML; they become their text. */
function unwrapLinks(node) {
  visit(node, 'link', (l, i, parent) => {
    if (!parent || i === undefined) return;
    parent.children.splice(i, 1, ...l.children);
    return [SKIP, i];
  });
}

function firstLink(node) {
  let href;
  visit(node, 'link', (l) => {
    href ??= l.url;
  });
  return href;
}

/** A table: one card per row, the first cell its title, the row's first link its target, the next cell its text. */
function tableToCards(table) {
  const [head, ...rows] = table.children;
  const labels = head.children.map((c) => mdToString(c).trim());
  return rows.map((row) => {
    const href = firstLink(row);
    const linkOnly = row.children.map(
      (c) => c.children.length === 1 && c.children[0].type === 'link' && c.children[0].url === href,
    );
    if (href) unwrapLinks(row);
    const [titleCell, ...cells] = row.children;
    const body = [];
    cells.forEach((cell, j) => {
      if (!cell.children.length || linkOnly[j + 1]) return;
      const label = { type: 'strong', children: [{ type: 'text', value: `${labels[j + 1]}: ` }] };
      body.push({ type: 'paragraph', children: body.length ? [label, ...cell.children] : cell.children });
    });
    return jsx('SummaryCard', { title: mdToString(titleCell).trim(), href }, body);
  });
}

/**
 * A list: one card per item. The item's opening strong text or link is its title (`**Agents**: text` or
 * `[Agents](agents.md): text`), the rest its text.
 */
function listToCards(list) {
  return list.children.map((item) => {
    const [para, ...rest] = item.children;
    const kids = para?.type === 'paragraph' ? [...para.children] : [];
    let title = '';
    let href;
    const lead = kids[0];
    if (lead && (lead.type === 'strong' || lead.type === 'link')) {
      title = mdToString(lead).trim();
      if (lead.type === 'link') href = lead.url;
      else href = lead.children.find((c) => c.type === 'link')?.url;
      kids.shift();
      if (kids[0]?.type === 'text') kids[0] = { ...kids[0], value: kids[0].value.replace(/^\s*[:—–-]\s*/, '') };
    } else {
      title = mdToString(para ?? item).split(/[:.]/)[0].trim();
    }
    const body = [];
    if (kids.length && mdToString({ type: 'paragraph', children: kids }).trim()) body.push({ type: 'paragraph', children: kids });
    body.push(...rest);
    const card = jsx('SummaryCard', { title, href }, body);
    if (href) unwrapLinks(card);
    return card;
  });
}

/**
 * @param {{ throwOnError?: boolean }} [options] throwOnError: throw on a broken link (the build) or only record it on
 *   file.data.opsAi (the link check)
 */
export function remarkOpsAi(options = {}) {
  const throwOnError = options.throwOnError ?? true;

  return (tree, file) => {
    if (!file.path) return;
    const idx = repoIndex();
    const source = path.relative(idx.root, path.resolve(file.path)).split(path.sep).join('/');
    if (!isSitePage(source)) return;
    const dir = path.posix.dirname(source);
    const ownAnchors = idx.pages[source]?.anchors ?? [];
    const errors = [];
    const at = (url) => `${source} -> ${url}`;

    // Title: the first `# heading`, which the page header shows instead.
    const h1 = tree.children.findIndex((n) => n.type === 'heading' && n.depth === 1);
    if (h1 >= 0) {
      const frontmatter = (file.data.frontmatter ??= {});
      frontmatter.title ??= mdToString(tree.children[h1]).trim();
      tree.children.splice(h1, 1);
    }

    // Links
    visit(tree, 'link', (node) => {
      const url = node.url;
      if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//')) return;
      if (url.startsWith('#')) {
        if (!ownAnchors.includes(decodeURIComponent(url.slice(1)))) errors.push(`${at(url)}: no such heading`);
        return;
      }
      if (url.startsWith('/')) {
        errors.push(`${at(url)}: absolute path; link relative to the file instead`);
        return;
      }
      const [p, hash = ''] = url.split(/(?=#)/);
      const target = resolveRepoPath(path.posix.normalize(path.posix.join(dir, decodeURI(p))), hash);
      if (target.url) node.url = target.url;
      else errors.push(`${at(url)}: ${target.broken}`);
    });

    // Code refs. A page here wins; otherwise code at the repo root before a docs folder of the same name.
    visit(tree, 'inlineCode', (node, index, parent) => {
      if (!parent || index === undefined || parent.type === 'link') return;
      const v = node.value.trim();
      const match = v.match(CODE_PATH);
      if (!match || !/[/.]/.test(v) || /^\d/.test(v) || v === '.' || v === '..') return;
      const [, line, end] = match;
      const bare = v.replace(/:\d+(-\d+)?$/, '');
      const lines = line ? `${line}${end ? `-L${end}` : ''}` : undefined;
      const atBase = (base) => {
        const c = path.posix.normalize(path.posix.join(base, bare));
        return c.startsWith('..') || c === '.' ? undefined : c;
      };
      const bases = /^\.{1,2}\//.test(bare) ? [dir] : [dir, 'docs', ''];
      const isPage = (c) => idx.pages[c] || idx.pages[`${c.replace(/\/$/, '')}/README.md`];
      const ordered = [
        ...bases.map(atBase).filter((c) => c && isPage(c)),
        ...(bases.length === 1 ? bases : ['', dir, 'docs']).map(atBase).filter(Boolean),
      ];
      for (const candidate of ordered) {
        const target = resolveRepoPath(candidate, '', lines);
        if (target.url) {
          parent.children[index] = { type: 'link', url: target.url, children: [node] };
          return SKIP;
        }
      }
    });

    // Status line.
    const firstIndex = tree.children.findIndex((n) => n.type === 'paragraph');
    const first = tree.children[firstIndex];
    const lead = first?.children[0];
    if (firstIndex >= 0 && firstIndex <= 1 && lead?.type === 'text' && /^Status:\s*/.test(lead.value)) {
      lead.value = lead.value.replace(/^Status:\s*/, '');
      // The badge carries a short opening clause ("proposed design"), so the sentence after it reads whole.
      const clause = lead.value.match(/^([^.,;:(]+?)\s*(?:[.,;:]\s*|(?=\())/);
      const word = lead.value.match(STATUS_WORDS)?.[1]?.toLowerCase();
      let label = word;
      if (word && clause && clause[1].split(/\s+/).length <= 4) {
        label = clause[1].toLowerCase();
        lead.value = lead.value.slice(clause[0].length);
      } else if (word) {
        takeWord(first.children, STATUS_WORDS);
      }
      if (lead.value) lead.value = lead.value.charAt(0).toUpperCase() + lead.value.slice(1);
      tree.children[firstIndex] = jsx('DocStatus', { status: word ?? 'note', label }, [first]);
    }

    // Badges in table cells.
    visit(tree, 'table', (table) => {
      for (const row of table.children.slice(1)) {
        for (const cell of row.children) {
          const status = takeWord(cell.children, BADGE);
          if (!status) continue;
          const rest = cell.children.length ? [{ type: 'text', value: ' ' }] : [];
          cell.children.unshift(jsx('StatusBadge', { status }, [], false), ...rest);
        }
      }
    });

    // Markers: an HTML comment above a block.
    visit(tree, 'html', (n, i, parent) => {
      const kind = n.value.trim().match(/^<!--\s*site:\s*(cards|steps)\s*-->$/)?.[1];
      if (!kind || !parent || i === undefined) return;
      const next = parent.children[i + 1];
      if (kind === 'steps') {
        if (next?.type !== 'list' || !next.ordered) {
          errors.push(`${source}: <!-- site: steps --> must sit directly above a numbered list`);
          return;
        }
        parent.children.splice(i, 2, jsx('Steps', {}, next.children.map((item) => jsx('Step', {}, item.children))));
        return [SKIP, i];
      }
      if (next?.type === 'table') parent.children.splice(i, 2, jsx('SummaryCards', {}, tableToCards(next)));
      else if (next?.type === 'list') parent.children.splice(i, 2, jsx('SummaryCards', {}, listToCards(next)));
      else {
        errors.push(`${source}: <!-- site: cards --> must sit directly above a table or a list`);
        return;
      }
      return [SKIP, i];
    });

    // Callouts from GitHub alerts.
    visit(tree, 'blockquote', (node, i, parent) => {
      const para = node.children[0];
      const text = para?.type === 'paragraph' && para.children[0]?.type === 'text' ? para.children[0] : undefined;
      const m = text?.value.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/);
      if (!m || !parent || i === undefined) return;
      text.value = text.value.slice(m[0].length);
      if (!text.value) para.children.shift();
      if (para.children[0]?.type === 'break') para.children.shift();
      const title = m[1].charAt(0) + m[1].slice(1).toLowerCase();
      parent.children[i] = jsx('Callout', { type: ALERTS[m[1]], title }, node.children);
      return SKIP;
    });

    // Diagrams and figures.
    visit(tree, (node, i, parent) => {
      if (!parent || i === undefined) return;
      if (node.type === 'code' && node.lang === 'mermaid') {
        parent.children[i] = jsx('OpsMermaid', { chart: node.value });
        return SKIP;
      }
      if (node.type !== 'paragraph' || parent.type !== 'root') return;
      const kids = node.children.filter((c) => !(c.type === 'text' && !c.value.trim()));
      if (kids.length !== 1 || kids[0].type !== 'image') return;
      const img = kids[0];
      const src = /^[a-z]+:/i.test(img.url) ? undefined : path.posix.normalize(path.posix.join(dir, img.url));
      const diagram = src?.match(/^docs\/diagrams\/([\w-]+)\.svg$/)?.[1];
      if (diagram && idx.files.has(`docs/diagrams/${diagram}.yaml`)) {
        parent.children[i] = jsx('BoxDiagram', { name: diagram, caption: img.alt || undefined });
      } else {
        parent.children[i] = jsx('OpsFigure', { caption: img.alt || undefined }, [node]);
      }
      return SKIP;
    });

    // A standalone HTML page is a plain file, not a route: a native link, so the router never prefetches it.
    visit(tree, 'link', (node, i, parent) => {
      if (!node.url.startsWith('/files/') || !parent || i === undefined) return;
      parent.children[i] = jsx('FileLink', { href: node.url }, node.children, false);
      return SKIP;
    });

    file.data.opsAi = { source, errors };
    if (throwOnError && errors.length) {
      throw new Error(`ops-ai docs: ${errors.length} broken link(s)\n  ${errors.join('\n  ')}`);
    }
  };
}
