/**
 * The markdown half of the figure library: what each `<!-- site: <kind> ... -->` marker reads from the block below it,
 * and the component it becomes. src/lib/remark-ops-ai.mjs calls figureFromMarker() for every marker; the components
 * live beside this file and are mapped in ./index.ts. Authors' rules: docs/contributing/figure-guide.md, every figure
 * with its source: docs/contributing/figures.md.
 *
 * Each parser gets the nodes after the marker and returns { data, take } (how many nodes it consumed) or { error }.
 */
import { toString as mdToString } from 'mdast-util-to-string';

/** `**Lead**: rest` as { lead, rest }, both plain text; a paragraph with no bold opening has no lead. */
function leadAndRest(para) {
  const kids = para?.type === 'paragraph' ? para.children : [];
  const first = kids[0];
  if (!first || first.type !== 'strong') return { lead: '', rest: mdToString(para ?? { type: 'text', value: '' }).trim() };
  const rest = mdToString({ type: 'paragraph', children: kids.slice(1) }).replace(/^\s*[:—–-]\s*/, '').trim();
  return { lead: mdToString(first).trim(), rest };
}

/** "Inbox · A dispute arrives" as the screen's surface and its title. */
function surfaceAndTitle(lead) {
  const [surface, ...title] = lead.split(/\s+·\s+/);
  return title.length ? { surface, title: title.join(' · ') } : { surface: '', title: lead };
}

const nestedList = (item) => item.children.find((c) => c.type === 'list');
const nestedItems = (item) => nestedList(item)?.children ?? [];
const firstNote = (item) => {
  const list = nestedList(item);
  return list ? mdToString(list.children[0]).trim() : undefined;
};
const itemText = (item) => leadAndRest(item.children[0]);

/** A screen's fields from list items: `**Label**: value`, a code block as the value, a nested bullet as the note. */
function fragmentFields(items) {
  const fragment = { fields: [], actions: [] };
  for (const item of items) {
    const { lead, rest } = itemText(item);
    if (/^actions?$/i.test(lead)) {
      fragment.actions = rest.split(/\s*,\s*/).filter(Boolean);
      fragment.actionsNote = firstNote(item);
      continue;
    }
    const code = item.children.find((c) => c.type === 'code')?.value;
    fragment.fields.push({ label: lead, value: rest, code, note: firstNote(item) });
  }
  return fragment;
}

const list = (nodes, { ordered, min, max, what = 'items' } = {}) => {
  const node = nodes[0];
  if (node?.type !== 'list') return { error: 'must sit directly above a list' };
  if (ordered && !node.ordered) return { error: 'must sit directly above a numbered list' };
  const n = node.children.length;
  if ((min && n < min) || (max && n > max)) return { error: `takes ${min === max ? min : `${min} to ${max}`} ${what}; found ${n}` };
  return { items: node.children };
};

/** One screen with numbered notes: the first item names it, the rest are its rows. Annotated screen and widget. */
function screen(nodes) {
  const { items, error } = list(nodes, { min: 2 });
  if (error) return { error };
  const [head, ...rows] = items;
  const { lead, rest } = itemText(head);
  const data = { ...surfaceAndTitle(lead), text: rest || undefined, ...fragmentFields(rows) };
  const notes = data.fields.filter((f) => f.note).length + (data.actionsNote ? 1 : 0);
  if (notes > 5) return { error: `has ${notes} notes; at most 5` };
  return { data, take: 1 };
}

/** The console's own sidebar, so a preview shows the product's real navigation (apps/console/src/lib/nav.ts). */
export const CONSOLE_NAV = [
  { group: 'Work', items: ['Overview', 'Cases', 'Human Tasks'] },
  { group: 'Build', items: ['Agents', 'Workflows', 'Channels', 'Skills', 'Guardrails'] },
  { group: 'Data', items: ['Knowledge bases', 'Tools', 'Files', 'Document types'] },
  { group: 'Govern', items: ['Activity', 'Reviews', 'Access', 'Policies', 'Settings'] },
];
const NAV_ITEMS = CONSOLE_NAV.flatMap((g) => g.items);
const ARROW = /\s*(?:→|->)\s*/;
const TONES = [
  [/fail|stuck|declin|reject|cancel|expir|refus|error/i, 'stop'],
  [/done|publish|credit|approv|complet|succeed|live|closed|sent/i, 'done'],
];
const toneOf = (name) => TONES.find(([re]) => re.test(name))?.[1];

const PARSERS = {
  journey(nodes) {
    const { items, error } = list(nodes, { ordered: true, min: 2, max: 6, what: 'steps' });
    if (error) return { error };
    return {
      take: 1,
      data: items.map((item) => {
        const { lead, rest } = itemText(item);
        return { ...surfaceAndTitle(lead), callout: rest, ...fragmentFields(nestedItems(item)) };
      }),
    };
  },
  annotated: screen,
  widget: screen,
  layers(nodes) {
    const { items, error } = list(nodes, { min: 2 });
    if (error) return { error };
    return {
      take: 1,
      data: items.map((item) => {
        const { lead, rest } = itemText(item);
        const parts = nestedItems(item).map((p) => {
          const part = itemText(p);
          return part.lead ? { title: part.lead, text: part.rest || undefined } : { title: part.rest };
        });
        return { title: lead || rest, text: lead ? rest || undefined : undefined, parts };
      }),
    };
  },
  'before-after'(nodes) {
    const { items, error } = list(nodes, { min: 2, max: 2, what: 'sides' });
    if (error) return { error };
    const sides = items.map((item) => {
      const { lead, rest } = itemText(item);
      return { label: lead, text: rest || undefined, points: nestedItems(item).map((p) => mdToString(p).trim()) };
    });
    if (sides.some((s) => !s.label)) return { error: 'each side opens with its label in bold: `- **Today**: ...`' };
    return { data: sides, take: 1 };
  },
  sequence(nodes) {
    const { items, error } = list(nodes, { ordered: true, min: 2, max: 12, what: 'messages' });
    if (error) return { error };
    const actors = [];
    const steps = [];
    for (const item of items) {
      const { lead, rest } = itemText(item);
      const ends = lead.split(ARROW);
      if (ends.length !== 2 || !ends[0] || !ends[1]) return { error: `"${lead}" needs **From → To** in bold` };
      for (const a of ends) if (!actors.includes(a)) actors.push(a);
      steps.push({ from: actors.indexOf(ends[0]), to: actors.indexOf(ends[1]), text: rest, note: firstNote(item) });
    }
    if (actors.length > 5) return { error: `has ${actors.length} participants; at most 5 fit at 390 wide` };
    return { data: { actors, steps }, take: 1 };
  },
  state(nodes) {
    const { items, error } = list(nodes, { min: 2, max: 7, what: 'states' });
    if (error) return { error };
    const states = items.map((item) => {
      const { lead, rest } = itemText(item);
      const next = nestedItems(item).map((t) => {
        const { lead: to, rest: when } = itemText(t);
        return { to: to.replace(/^(?:→|->)\s*/, ''), when };
      });
      return { name: lead, text: rest || undefined, next };
    });
    const names = states.map((s) => s.name);
    for (const s of states) {
      if (!s.name) return { error: 'each state opens with its name in bold' };
      for (const t of s.next) if (!names.includes(t.to)) return { error: `"${s.name}" moves to "${t.to}", which is not a state in the list` };
    }
    return { data: states.map((s) => ({ ...s, tone: s.next.length ? undefined : (toneOf(s.name) ?? 'done') })), take: 1 };
  },
  decision(nodes) {
    const { items, error } = list(nodes, { min: 1, max: 1, what: 'question' });
    if (error) return { error };
    let problem;
    const ask = (item, depth) => {
      const { lead, rest } = itemText(item);
      const branches = nestedItems(item).map((b) => {
        const { lead: answer, rest: outcome } = itemText(b);
        const follow = nestedItems(b)[0];
        if (!answer) problem ??= `an answer under "${lead}" needs its label in bold: \`- **Yes**: ...\``;
        if (follow && depth >= 2) problem ??= 'goes deeper than three questions; split it or use a table';
        return { answer, outcome: outcome || undefined, next: follow && depth < 2 ? ask(follow, depth + 1) : undefined };
      });
      if (branches.length < 2 || branches.length > 3) problem ??= `"${lead || rest}" needs two or three answers`;
      return { question: lead || rest, text: lead ? rest || undefined : undefined, branches };
    };
    const data = ask(items[0], 0);
    return problem ? { error: problem } : { data, take: 1 };
  },
  compare(nodes, attr) {
    const { items, error } = list(nodes, { min: 2, max: 3, what: 'options' });
    if (error) return { error };
    const options = items.map((item) => {
      const { lead, rest } = itemText(item);
      return { name: lead, text: rest || undefined, rows: nestedItems(item).map((r) => ({ label: itemText(r).lead, value: itemText(r).rest })) };
    });
    const pick = attr('pick');
    if (pick && !options.some((o) => o.name === pick)) return { error: `pick="${pick}" names no option` };
    return { data: { options, pick }, take: 1 };
  },
  timeline(nodes) {
    const { items, error } = list(nodes, { min: 3, max: 6, what: 'moments' });
    if (error) return { error };
    const points = items.map((item) => {
      const { lead, rest } = itemText(item);
      return { when: lead, text: rest, note: firstNote(item) };
    });
    if (points.some((p) => !p.when)) return { error: 'each moment opens with its time in bold: `- **15 minutes**: ...`' };
    return { data: points, take: 1 };
  },
  exchange(nodes) {
    const [req, res] = nodes;
    if (req?.type !== 'code' || res?.type !== 'code') return { error: 'must sit directly above two code blocks, the request and then the response' };
    const meta = (node, name) => node.meta?.match(new RegExp(`${name}="([^"]*)"`))?.[1];
    return {
      take: 2,
      data: {
        request: { lang: req.lang ?? '', title: meta(req, 'title') ?? 'Request', code: req.value },
        response: { lang: res.lang ?? '', title: meta(res, 'title') ?? 'Response', code: res.value, status: meta(res, 'status') },
      },
    };
  },
  preview(nodes) {
    const { items, error } = list(nodes, { min: 2 });
    if (error) return { error };
    const [head, ...rest] = items;
    const { lead, rest: text } = itemText(head);
    const { surface, title } = surfaceAndTitle(lead);
    if (!NAV_ITEMS.includes(surface)) return { error: `"${surface}" is not a console sidebar item (${NAV_ITEMS.join(', ')})` };
    const data = { surface, title, text: text || undefined, columns: [], rows: [], panel: undefined };
    for (const item of rest) {
      const { lead: key, rest: value } = itemText(item);
      if (/^columns$/i.test(key)) data.columns = value.split(/\s*,\s*/);
      else if (/^row$/i.test(key)) data.rows.push({ cells: value.split(/\s*,\s*/), note: firstNote(item) });
      else if (/^panel\b/i.test(key)) data.panel = { surface, title: surfaceAndTitle(key).title, text: value || undefined, ...fragmentFields(nestedItems(item)) };
      else return { error: `"${key}" is not a preview row; use **Columns**, **Row** or **Panel · Title**` };
    }
    if (!data.columns.length || !data.rows.length) return { error: 'needs **Columns** and at least one **Row**' };
    if (data.rows.some((r) => r.cells.length !== data.columns.length)) return { error: 'every **Row** has one value per column' };
    return { data, take: 1 };
  },
};

/** The component each marker kind becomes; ./index.ts maps the same names for MDX. */
export const FIGURE_COMPONENTS = {
  journey: 'JourneyFigure',
  annotated: 'AnnotatedFigure',
  widget: 'WidgetFigure',
  layers: 'LayerMap',
  'before-after': 'BeforeAfterFigure',
  sequence: 'SequenceFigure',
  state: 'StateFigure',
  decision: 'DecisionFigure',
  compare: 'CompareFigure',
  timeline: 'TimelineFigure',
  exchange: 'ExchangeFigure',
  preview: 'PreviewFigure',
};
export const FIGURE_KINDS = Object.keys(FIGURE_COMPONENTS);

/**
 * A marker's figure: { component, props, take } or { error }. `attrs` is the text after the kind; `caption` is
 * required because it is the figure's accessible name.
 */
export function figureFromMarker(kind, attrs, nodes) {
  const attr = (name) => attrs.match(new RegExp(`${name}="([^"]*)"`))?.[1];
  const parsed = PARSERS[kind](nodes, attr);
  if (parsed.error) return parsed;
  const caption = attr('caption');
  if (!caption) return { error: 'needs caption="...", which is also its accessible name' };
  return {
    component: FIGURE_COMPONENTS[kind],
    props: { data: JSON.stringify(parsed.data), caption, frame: attr('frame') },
    take: parsed.take,
    showSource: /(?:^|\s)source(?:\s|$)/.test(attrs.replace(/"[^"]*"/g, '""')),
  };
}
