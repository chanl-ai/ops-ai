// uc-781 Record editors and list pages share one header, one tab strip and one section style, ui layer:
// docs/usecases/console/editor-page-layout.md. Demo stack; James (builder) and Rohan (viewer) at 1440 and 390.
import { check, chromium, consoleSignIn, expectSampleData, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD } from '@ops-ai/usecase-runner/steps';

// The model inventory and some lists are still answered by the console's mock.
expectSampleData('/govern/models', '/data/knowledge', '/build/skills', '/data/connectors', '/build/agents', '/build/workflows');

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** Runs in the page: the geometry the checks read. */
function measure() {
  const main = document.querySelector('main') ?? document.body;
  const box = (el) => (el ? el.getBoundingClientRect() : null);
  const title = main.querySelector('[data-testid=page-title]');
  const input = title?.querySelector('input');
  const description = main.querySelector('[data-testid=page-description]');
  const icon = main.querySelector('[data-testid=page-header] > div > div, [data-testid=page-back-icon]');
  const textLeft = (el) => {
    if (!el) return null;
    const i = el.querySelector('input');
    if (i) {
      const s = getComputedStyle(i);
      return box(i).left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft);
    }
    return box(el).left;
  };
  const actions = main.querySelector('[data-testid=page-actions]');
  const kids = actions ? [...actions.children].flatMap((c) => (getComputedStyle(c).display === 'contents' ? [...c.children] : [c])).filter((c) => box(c).width > 0) : [];
  const rows = [...new Set(kids.map((k) => Math.round(box(k).top / 8)))];
  const save = main.querySelector('[data-testid=save-state]');
  const saveBtn = main.querySelector('[data-testid=agent-save], [data-testid=definition-save], [data-testid=record-save]');
  const tabsRow = main.querySelector('[data-testid=page-tabs-row]');
  const strips = main.querySelectorAll('[data-slot=tabs-list], nav[aria-label="Page sections"] ul, [data-testid=section-tabs]');
  const headings = [...main.querySelectorAll('h2, [data-field] [role=heading]')].filter((h) => h.closest('section, [data-testid=instruction-document], .rounded-lg') && h.dataset.testid !== 'page-title' && !h.closest('[data-testid=page-header], [data-testid=agent-test-panel], [role=dialog]') && box(h).width > 0);
  // Where a section heading starts: absolute, for the cards that sit directly on the page (a card inside a card is nested one step in).
  const topLevel = headings.filter((h) => { const card = h.closest('.rounded-lg'); return card && !card.parentElement.closest('.rounded-lg'); });
  const headingLefts = topLevel.map((h) => Math.round(box(h).left));
  const crumbs = [...document.querySelectorAll('nav[aria-label=Breadcrumb] > span')];
  return {
    h1: main.querySelectorAll('h1').length,
    scrollsSideways: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    titleLeft: textLeft(title),
    descriptionLeft: description ? box(description).left : null,
    iconTop: icon ? box(icon).top : null,
    titleTop: title ? box(title).top : null,
    actionRows: rows.length,
    saveTop: save ? box(save).top : null,
    saveBtnTop: saveBtn ? box(saveBtn).top : null,
    strips: strips.length,
    tabsScroll: tabsRow ? { client: tabsRow.clientWidth, scroll: tabsRow.scrollWidth } : null,
    headingLefts,
    headingSizes: [...new Set(headings.map((h) => getComputedStyle(h).fontSize))],
    lastCrumb: crumbs.at(-1)?.lastElementChild?.textContent?.trim() ?? null,
    headingInfo: topLevel.map((h, i) => `${h.textContent.trim().slice(0, 18)}:${headingLefts[i]}`),
    tabsList: (() => { const l = tabsRow?.querySelector('[data-slot=tabs-list]'); return l ? { w: Math.round(box(l).width), cw: getComputedStyle(l).width, ov: getComputedStyle(tabsRow).overflowX } : null; })(),
    titleText: title?.querySelector('input')?.value ?? title?.textContent?.trim() ?? null,
  };
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      for (const [who, email, builder] of [['James', 'j.richardson@harborpine.example', true], ['Rohan', 'r.menon@harborpine.example', false]]) {
        const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
        page.setDefaultTimeout(30_000);
        const open = async (path) => {
          await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.locator('main h1').first().waitFor();
          await page.waitForLoadState('networkidle').catch(() => {});
        };
        const first = async (list, prefix) => {
          await open(list);
          const href = await page.locator(`main a[href^="${prefix}"]`).first().getAttribute('href');
          return href.split('?')[0];
        };
        const agent = await first('/build/agents', '/build/agents/');
        const workflow = await first('/build/workflows', '/build/workflows/definitions/');
        // A record that does not exist is a whole-page state; it still has its one h1.
        const pages = ['/build/agents', agent, workflow, '/data/connectors', '/build/skills', '/govern/models', '/build/agents/ag_does_not_exist'];

        for (const width of [1440, 390]) {
          await page.setViewportSize({ width, height: 1000 });
          const tag = `${who} ${width}`;

          await step(`1 ${tag} header and page basics`, async () => {
            const bad = [];
            for (const path of pages) {
              await open(path);
              const m = await page.evaluate(measure);
              if (m.h1 !== 1) bad.push(`${path}: ${m.h1} h1`);
              if (m.scrollsSideways) bad.push(`${path}: page scrolls sideways`);
              if (m.descriptionLeft !== null && Math.abs(m.descriptionLeft - m.titleLeft) > 1) bad.push(`${path}: title ${m.titleLeft} and description ${m.descriptionLeft} differ`);
              if (m.iconTop !== null && Math.abs(m.iconTop - m.titleTop) > 8) bad.push(`${path}: icon top ${m.iconTop}, title top ${m.titleTop}`);
            }
            check(`1 ${tag} one h1, no sideways scroll, title and description on one edge, icon level with the title`, !bad.length, bad);
          });

          await step(`2 ${tag} one tab strip on the workflow editor`, async () => {
            await open(workflow);
            const m = await page.evaluate(measure);
            check(`2 ${tag} the workflow editor has one tab strip`, m.strips === 1, m.strips);
          });

          await step(`3 ${tag} save state and actions in one row`, async () => {
            await open(agent);
            const m = await page.evaluate(measure);
            const ok = builder ? m.actionRows === 1 && m.saveTop !== null && Math.abs(m.saveTop - m.saveBtnTop) <= 6 && m.lastCrumb === m.titleText : m.lastCrumb === m.titleText;
            check(`3 ${tag} the agent's actions share one row and the breadcrumb names the agent`, ok, m);
          });

          await step(`4 ${tag} the agent tab strip reaches every tab`, async () => {
            await open(agent);
            const reach = await page.evaluate(() => {
              const row = document.querySelector('[data-testid=page-tabs-row]');
              const tabs = [...row.querySelectorAll('[role=tab]')];
              row.scrollLeft = row.scrollWidth;
              const r = row.getBoundingClientRect();
              const last = tabs.at(-1).getBoundingClientRect();
              row.scrollLeft = 0;
              const first = tabs[0].getBoundingClientRect();
              return { last: last.right <= r.right + 1, first: first.left >= r.left - 1, tabs: tabs.length, scroll: row.scrollWidth, client: row.clientWidth, list: row.querySelector('[data-slot=tabs-list]')?.getBoundingClientRect().width };
            });
            check(`4 ${tag} the first and last tab can be scrolled into view`, reach.last && reach.first, reach);
          });

          await step(`5 ${tag} agent sections share one heading`, async () => {
            const sizes = new Set();
            const lefts = new Set();
            const notes = [];
            const info = [];
            for (const tab of ['settings', 'evals', 'channels', 'limits']) {
              await open(`${agent}/${tab}`);
              const m = await page.evaluate(measure);
              m.headingSizes.forEach((s) => sizes.add(s));
              m.headingLefts.forEach((l) => lefts.add(l));
              info.push(tab + ': ' + m.headingInfo.join(' | '));
              if (tab === 'limits') {
                const w = await page.evaluate(() => {
                  const c = document.querySelector('[data-testid=agent-limits]');
                  const main = document.querySelector('[data-testid=page-header]').getBoundingClientRect();
                  return [Math.round(c.getBoundingClientRect().width), Math.round(main.width)];
                });
                if (w[0] < w[1] - 4) notes.push(`limits ${w[0]} of ${w[1]}`);
              }
              if (tab === 'evals' && builder && width >= 1024) {
                const run = page.getByTestId('add-eval-case-button');
                if (await run.count()) {
                  const [bt, ht] = await page.evaluate(() => [document.querySelector('[data-testid=add-eval-case-button]').getBoundingClientRect().top, [...document.querySelectorAll('h2')].find((h) => h.textContent === 'Latest run').getBoundingClientRect().top]);
                  if (Math.abs(bt - ht) > 16) notes.push(`evals buttons ${bt} vs heading ${ht}`);
                }
              }
              if (tab === 'settings') {
                const gap = await page.evaluate(() => {
                  const b = document.querySelector('[data-testid=agent-view-prompt]');
                  const card = b?.closest('[data-testid=instruction-document]');
                  return b && card ? Math.round(card.getBoundingClientRect().right - b.getBoundingClientRect().right) : null;
                });
                if (gap === null || gap > 20) notes.push(`view prompt ${gap}px from the card edge`);
              }
            }
            check(`5 ${tag} one heading size and left edge, Limits full width, buttons on the heading row, View prompt at the edge`, sizes.size === 1 && lefts.size === 1 && !notes.length, { sizes: [...sizes], lefts: [...lefts], notes, info });
          });

          // Rows of the header's actions: no action alone on its row (unless it spans the width), Saved beside Save.
          const rowsOf = () =>
            page.evaluate(() => {
              const wrap = document.querySelector('[data-testid=page-actions]');
              const flat = [...wrap.children].flatMap((c) => (getComputedStyle(c).display === 'contents' ? [...c.children] : [c])).filter((c) => c.getBoundingClientRect().width > 0);
              const rows = [];
              for (const el of flat) {
                const r = el.getBoundingClientRect();
                const row = rows.find((q) => r.top < q.bottom - 4 && q.top < r.bottom - 4);
                if (row) (row.items.push(r), (row.bottom = Math.max(row.bottom, r.bottom)));
                else rows.push({ top: r.top, bottom: r.bottom, items: [r] });
              }
              const w = wrap.getBoundingClientRect().width;
              const lone = rows.length > 1 ? rows.filter((q) => q.items.length === 1 && q.items[0].width < w * 0.9).length : 0;
              const save = document.querySelector('[data-testid=save-state]')?.getBoundingClientRect();
              const btn = document.querySelector('[data-testid=agent-save], [data-testid=definition-save]')?.getBoundingClientRect();
              const text = document.querySelector('[data-testid=save-state]');
              const range = text && document.createRange();
              if (range) range.selectNodeContents(text);
              const textRight = range ? range.getBoundingClientRect().right : null;
              return { rows: rows.map((q) => q.items.length), lone, gap: btn && textRight ? Math.round(btn.left - textRight) : null };
            });
          await step(`3b ${tag} actions wrap as one group and Saved sits beside Save`, async () => {
            const bad = [];
            for (const [name, path] of [['agent', agent], ['workflow', workflow]]) {
              await open(path);
              const r = await rowsOf();
              if (r.lone) bad.push(`${name}: a lone action on its own row ${JSON.stringify(r.rows)}`);
              if (width < 640 && r.rows.length > 2) bad.push(`${name}: the header takes ${r.rows.length} rows at 390`);
              if (builder && width >= 1024 && r.gap !== null && r.gap > 24) bad.push(`${name}: Saved is ${r.gap}px from Save`);
            }
            if (builder) {
              // Paused: the Pause button reads Resume and the lifecycle chip says Paused.
              await open(workflow);
              // On a phone Pause is in the header's menu, which a keyboard reaches like the desktop button.
              if (width < 640) {
                await page.getByTestId('definition-more').click();
                await page.getByTestId('definition-pause-menu').click();
              } else await page.getByTestId('definition-pause').click();
              await page.getByTestId('definition-pause-confirm').click();
              await page.getByTestId('definition-pause-confirm').waitFor({ state: 'hidden' });
              await page.getByTestId(width < 640 ? 'definition-more' : 'definition-resume').waitFor();
              const r = await rowsOf();
              if (r.lone) bad.push(`workflow paused: a lone action ${JSON.stringify(r.rows)}`);
              if (width < 640) {
                await page.getByTestId('definition-more').click();
                await page.getByTestId('definition-resume-menu').click();
              } else await page.getByTestId('definition-resume').click();
              await page.getByTestId('definition-pause-confirm').click();
              await page.getByTestId('definition-pause-confirm').waitFor({ state: 'hidden' });
              await page.getByTestId(width < 640 ? 'definition-more' : 'definition-pause').waitFor();
            }
            check(`3b ${tag} no action alone on its row, Saved beside Save`, !bad.length, bad);
          });

          if (builder) {
            await step(`6 ${tag} the step sheet stays in the panel`, async () => {
              await open(workflow);
              await page.locator('.react-flow__node').first().click();
              const sheet = page.getByTestId('step-sheet');
              await sheet.waitFor();
              await page.waitForTimeout(600);
              const g = await page.evaluate(() => {
                const s = document.querySelector('[data-testid=step-sheet]').getBoundingClientRect();
                const panel = (document.querySelector('[data-slot=sidebar-inset]') ?? document.querySelector('main')).getBoundingClientRect();
                const t = document.querySelector('[data-testid=detail-sheet-title]').getBoundingClientRect();
                const x = document.querySelector('[data-testid=step-sheet] button.absolute, [data-testid=step-sheet] > button')?.getBoundingClientRect();
                return { right: s.right, left: s.left, bottom: s.bottom, panelRight: panel.right, panelBottom: panel.bottom, closeMid: x ? x.top + x.height / 2 : null, titleMid: t.top + t.height / 2, win: window.innerWidth };
              });
              const inside = width >= 640 ? g.right <= g.panelRight + 0.5 && g.bottom <= g.panelBottom + 0.5 : g.left >= 14 && g.right <= g.win - 14;
              check(`6 ${tag} the step sheet lies inside the panel with its close button on the title line`, inside && g.closeMid !== null && Math.abs(g.closeMid - g.titleMid) <= 6, g);
            });
          }
        }
        await page.context().close();
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
