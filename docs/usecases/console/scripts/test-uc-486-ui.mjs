// uc-486 every workflow lays itself out cleanly, ui layer (c-486): docs/usecases/console/workflow-canvas-layout.md.
// The definition editor and the run canvas, signed in as James: the four demo workflows, the complaint triage seed (the
// widest), fifty steps saved with no positions, a workflow created with no positions, a dragged step and its reroute
// time, Tidy up and its Undo, a position-only save and publish, and a run's canvas. (The design mock this card was
// reviewed on was deleted in c-517; every check it carried runs here on the real editor.)
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const EDITOR_SHOTS = evidenceDir('486', 'editor');
const SHOTS = evidenceDir('486', 'timings');
// Routes are computed in a Web Worker after the canvas fits; this is how long a check waits for them to settle.
const SETTLE_MS = 2_000;

const signIn = async (browser, consoleUrl, width = 1440, height = 1000, who = JAMES) => {
  const page = await (await browser.newContext({ viewport: { width, height } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text()) && page.errors.push(m.text()));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(who);
  await page.getByLabel('Password').fill(PASSWORD);
  await page
    .getByRole('button', { name: /^Sign in/ })
    .first()
    .click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

/**
 * Fifty steps saved with no positions (the editor lays them out): a chain of tool steps, every third with a retry loop,
 * and every refused or failed call ending at one Failed step, as a saved workflow must.
 */
function fiftySteps() {
  const nodes = [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', parameters: { onlyFromWorkflows: false } },
    { id: 'failed', type: 'ops.flow.end', typeVersion: 1, name: 'Failed', parameters: { outcome: 'failed' } },
  ];
  const connections = [];
  const tool = (id, name) => nodes.push({ id, type: 'ops.action.tool', typeVersion: 1, name, parameters: { operation: 'get_customer' } });
  const toFailed = (id, ...ports) => ports.forEach((port) => connections.push({ from: { node: id, port }, to: { node: 'failed', port: 'in' } }));
  let last = 'start';
  let port = 'payload';
  for (let i = 1; nodes.length < 49; i++) {
    const id = `step_${i}`;
    tool(id, `Step ${i}`);
    connections.push({ from: { node: last, port }, to: { node: id, port: 'in' } });
    if (i % 3 === 0 && nodes.length < 48) {
      tool(`retry_${i}`, `Retry ${i}`);
      connections.push({ from: { node: id, port: 'refused' }, to: { node: `retry_${i}`, port: 'in' } });
      connections.push({ from: { node: `retry_${i}`, port: 'ok' }, to: { node: id, port: 'in' } });
      toFailed(`retry_${i}`, 'refused', 'error');
      toFailed(id, 'error');
    } else toFailed(id, 'refused', 'error');
    last = id;
    port = 'ok';
  }
  nodes.push({ id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'done' } });
  connections.push({ from: { node: last, port }, to: { node: 'done', port: 'in' } });
  return { schemaVersion: 2, id: 'uc486_fifty', name: 'Fifty steps', nodes, connections };
}

// Step rects and each line's path sampled every 4 px, all in screen pixels. A line's id is `from:port->to:port`.
const geometry = (page, root) =>
  page.evaluate((root) => {
    const steps = [...document.querySelectorAll(`${root} [data-testid=definition-node]`)].map((el) => {
      const r = el.getBoundingClientRect();
      const title = el.querySelector('[data-testid=node-title]');
      const repeats = el.querySelector('[data-testid=node-repeats]');
      return {
        id: el.getAttribute('data-node-id'),
        x: r.left,
        y: r.top,
        w: r.width,
        h: r.height,
        // Unscaled, so the size check compares with the layout's own pixels at any zoom.
        drawnHeight: el.offsetHeight,
        layoutHeight: Number(el.getAttribute('data-layout-height') ?? NaN),
        titleCut: !!title && (title.scrollHeight > title.clientHeight + 1 || title.scrollWidth > title.clientWidth + 1),
        repeatsCut: !!repeats && repeats.scrollWidth > repeats.clientWidth + 1,
      };
    });
    const lines = [...document.querySelectorAll(`${root} .react-flow__edge`)].map((g) => {
      const id = (g.getAttribute('data-id') ?? g.getAttribute('data-testid')?.replace(/^rf__edge-/, '') ?? '').trim();
      const path = g.querySelector('path.react-flow__edge-path') ?? g.querySelector('path');
      const m = path.getScreenCTM();
      const len = path.getTotalLength();
      const points = [];
      for (let at = 0; at <= len; at += 4) {
        const p = path.getPointAtLength(at);
        points.push([m.a * p.x + m.c * p.y + m.e, m.b * p.x + m.d * p.y + m.f]);
      }
      const [from, to] = id.split('->');
      return { id, d: path.getAttribute('d'), source: from?.split(':')[0], target: to?.split(':')[0], points };
    });
    const t = getComputedStyle(document.querySelector(`${root} .react-flow__viewport`)).transform;
    const zoom = t && t !== 'none' ? new DOMMatrixReadOnly(t).a : 1;
    const canvas = document.querySelector(root).getBoundingClientRect();
    return { steps, lines, zoom, canvas: { x: canvas.left, y: canvas.top, w: canvas.width, h: canvas.height } };
  }, root);

const overlaps = (steps) => {
  const out = [];
  for (let i = 0; i < steps.length; i++)
    for (let j = i + 1; j < steps.length; j++) {
      const a = steps[i];
      const b = steps[j];
      if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) out.push(`${a.id}/${b.id}`);
    }
  return out;
};

// Lines that pass through a step other than their own two, inset 2 px so a line along a step's edge does not count.
const throughSteps = ({ steps, lines }) => {
  const out = new Set();
  for (const l of lines)
    for (const s of steps) {
      if (s.id === l.source || s.id === l.target) continue;
      if (l.points.some(([x, y]) => x > s.x + 2 && x < s.x + s.w - 2 && y > s.y + 2 && y < s.y + s.h - 2)) out.add(`${l.id} through ${s.id}`);
    }
  return [...out];
};

const clean = (name, g) => {
  const o = overlaps(g.steps);
  const t = throughSteps(g);
  check(`${name}: no two steps overlap`, g.steps.length > 0 && o.length === 0, o);
  check(`${name}: no line passes through a step`, g.lines.length > 0 && t.length === 0, t.slice(0, 8));
};

await withUiStack(
  async (consoleUrl) => {
    mkdirSync(SHOTS, { recursive: true });
    mkdirSync(EDITOR_SHOTS, { recursive: true });
    const browser = await chromium.launch();
    const timings = [];
    try {
      const tokenFor = async (email) =>
        (
          await (
            await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
          ).json()
        ).data.token;
      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const save = async (definition) => (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: H, body: JSON.stringify({ definition }) })).json();
      // A fresh stack has no team workflows, so the three seeds and the card dispute are saved as the demo seeds them.
      const seeds = JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8'));
      const seed = (id) => {
        const { teamId: _team, ...definition } = (Array.isArray(seeds) ? seeds : (seeds.workflows ?? Object.values(seeds))).find((w) => w.id === id);
        return definition;
      };
      for (const id of ['mail_intake', 'mail_document', 'levy_case', 'complaint_triage']) await save(seed(id));
      const fiftySaved = await save(fiftySteps());
      const card = JSON.parse(readFileSync(join(ROOT, 'scripts/sample-team/workflows/card_dispute_intake.json'), 'utf8'));
      const cardSaved = await save(card);
      // levy_case as a workflow created by API with no positions: the engine stores every step at {0, 0}.
      const levyDef = seed('levy_case');
      const unplaced = {
        ...levyDef,
        id: 'uc486_unplaced',
        name: 'Unplaced levy case',
        nodes: levyDef.nodes.map(({ position: _p, ...n }) => (n.type === 'ops.trigger.request' ? { ...n, parameters: { ...n.parameters, onlyFromWorkflows: false } } : n)),
      };
      const unplacedSaved = await save(unplaced);
      // The card dispute as staging stored it before steps grew to 288 px: 240 px apart along one row, so they overlap.
      const oldSpacing = { ...card, id: 'uc486_old_spacing', name: 'Card dispute, old spacing', nodes: card.nodes.map((n, i) => ({ ...n, position: { x: i * 240, y: 0 } })) };
      await save(oldSpacing);
      check('E0 setup: the card dispute, fifty steps and an unplaced copy of the levy case are saved', !!cardSaved.data && !!unplacedSaved.data && !!fiftySaved.data, {
        card: cardSaved.error ?? 'ok',
        unplaced: unplacedSaved.error ?? 'ok',
        fifty: fiftySaved.error ?? 'ok',
      });

      const james = await signIn(browser, consoleUrl, 1280, 800, JAMES);
      const ROOT_SEL = '[data-testid=definition-canvas]';
      const openEditor = async (id) => {
        await james.goto(`${consoleUrl}/workflows/definitions/${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.locator(`${ROOT_SEL} [data-testid=definition-node]`).first().waitFor({ timeout: 120_000 });
        await james.waitForTimeout(SETTLE_MS);
      };
      const editorClean = (name, g) => clean(name, g);
      for (const id of ['mail_intake', 'mail_document', 'levy_case', 'complaint_triage', 'card_dispute_intake', 'uc486_fifty', 'uc486_unplaced', 'uc486_old_spacing']) {
        await openEditor(id);
        const g = await geometry(james, ROOT_SEL);
        const trigger = g.steps[0];
        const fits = g.steps.every((s) => s.x >= g.canvas.x - 1 && s.x + s.w <= g.canvas.x + g.canvas.w + 1);
        check(
          `${id}: opens fitted, or at zoom 0.65 or more with the trigger in the left third`,
          g.zoom >= 0.65 - 1e-6 && (fits || (trigger.x >= g.canvas.x && trigger.x < g.canvas.x + g.canvas.w / 3)),
          { zoom: g.zoom, trigger: trigger?.x, canvas: g.canvas },
        );
        editorClean(`${id} in the editor`, g);
        // The steps in view open centred top to bottom, not low with empty canvas above, wide workflows included.
        const inView = g.steps.filter((s) => s.x < g.canvas.x + g.canvas.w && s.x + s.w > g.canvas.x);
        const top = Math.min(...inView.map((s) => s.y));
        const bottom = Math.max(...inView.map((s) => s.y + s.h));
        if (bottom - top <= g.canvas.h)
          check(`${id}: opens centred top to bottom`, Math.abs((top + bottom) / 2 - (g.canvas.y + g.canvas.h / 2)) <= g.canvas.h * 0.1, { top, bottom, canvas: g.canvas });
        if (id === 'uc486_unplaced' || id === 'uc486_old_spacing') {
          await james.screenshot({ path: join(EDITOR_SHOTS, `${id}-1280.png`) });
          continue;
        }
        const off = g.steps.filter((s) => !(Math.abs(s.drawnHeight - s.layoutHeight) <= 2)).map((s) => `${s.id} ${s.drawnHeight}/${s.layoutHeight}`);
        check(`${id}: every step is drawn at the height the layout gave it`, off.length === 0, off);
        const cut = g.steps.filter((s) => s.titleCut || s.repeatsCut).map((s) => s.id);
        check(`${id}: no title or repeat line is cut off`, cut.length === 0, cut);
        await james.screenshot({ path: join(EDITOR_SHOTS, `${id}-1280.png`) });
        // Fifty steps in a row are wider than the canvas even at the editor's least zoom (0.1), so Fit to view cannot
        // show them all; the reroute check below covers that workflow.
        if (id === 'uc486_fifty') continue;
        await james.keyboard.press('1');
        await james.waitForTimeout(800);
        const whole = await geometry(james, ROOT_SEL);
        check(
          `${id}: Fit to view shows every step`,
          whole.steps.every((s) => s.x >= whole.canvas.x - 1 && s.y >= whole.canvas.y - 1 && s.x + s.w <= whole.canvas.x + whole.canvas.w + 1 && s.y + s.h <= whole.canvas.y + whole.canvas.h + 1),
        );
      }

      // Fifty steps: a step mid-chain dropped among the others has its lines routed clear of every step within 300 ms.
      await openEditor('uc486_fifty');
      const fifty = await geometry(james, ROOT_SEL);
      const dropped = fifty.steps.find((s) => s.id === 'step_10');
      const ownLines = fifty.lines.filter((l) => l.source === dropped.id || l.target === dropped.id).map((l) => l.id);
      await james.mouse.move(dropped.x + dropped.w / 2, dropped.y + 12);
      await james.mouse.down();
      await james.mouse.move(dropped.x + dropped.w / 2, dropped.y + 112, { steps: 6 });
      await james.mouse.move(dropped.x + dropped.w / 2, dropped.y + 212, { steps: 6 });
      const t0 = Date.now();
      await james.mouse.up();
      const rerouted = await james
        .waitForFunction(
          ([root, ids]) =>
            ids.every((lineId) => {
              const g = document.querySelector(`${root} .react-flow__edge[data-id="${CSS.escape(lineId)}"]`);
              const path = g?.querySelector('path.react-flow__edge-path') ?? g?.querySelector('path');
              if (!path) return false;
              const [from, to] = lineId.split('->').map((x) => x.split(':')[0]);
              const m = path.getScreenCTM();
              const len = path.getTotalLength();
              const steps = [...document.querySelectorAll(`${root} [data-testid=definition-node]`)];
              for (let at = 0; at <= len; at += 4) {
                const pt = path.getPointAtLength(at);
                const x = m.a * pt.x + m.c * pt.y + m.e;
                const y = m.b * pt.x + m.d * pt.y + m.f;
                for (const st of steps) {
                  const sid = st.getAttribute('data-node-id');
                  if (sid === from || sid === to) continue;
                  const r = st.getBoundingClientRect();
                  if (x > r.left + 2 && x < r.right - 2 && y > r.top + 2 && y < r.bottom - 2) return false;
                }
              }
              return true;
            }),
          [ROOT_SEL, ownLines],
          { timeout: 5_000, polling: 'raf' },
        )
        .then(
          () => Date.now() - t0,
          () => null,
        );
      await james.waitForTimeout(SETTLE_MS);
      clean('uc486_fifty: after dropping step_10', await geometry(james, ROOT_SEL));
      timings.push({ workflow: 'uc486_fifty', step: dropped.id, lines: ownLines.length, msToReroute: rerouted });
      check("uc486_fifty: a dropped step's lines are clear of every step within 300 ms", rerouted !== null && rerouted <= 300, rerouted);
      await james.screenshot({ path: join(EDITOR_SHOTS, 'uc486_fifty-after-drop-1280.png') });

      // Drag a step of levy_case 200 px down: its lines are routed again; then Tidy up, Undo, Tidy up and save.
      await openEditor('levy_case');
      const start = await geometry(james, ROOT_SEL);
      const moved = start.steps.find((s) => s.id === 'match') ?? start.steps[1];
      await james.mouse.move(moved.x + moved.w / 2, moved.y + 12);
      await james.mouse.down();
      await james.mouse.move(moved.x + moved.w / 2, moved.y + 112, { steps: 6 });
      await james.mouse.move(moved.x + moved.w / 2, moved.y + 212, { steps: 6 });
      await james.mouse.up();
      await james.waitForTimeout(SETTLE_MS);
      const afterDrag = await geometry(james, ROOT_SEL);
      editorClean('levy_case after a drag', afterDrag);
      // A step's place relative to the trigger in canvas pixels, so a refit between readings does not matter.
      const rel = (g, id) => {
        const s = g.steps.find((x) => x.id === id);
        const t = g.steps[0];
        return s && { x: Math.round((s.x - t.x) / g.zoom), y: Math.round((s.y - t.y) / g.zoom) };
      };
      const dragged = rel(afterDrag, moved.id);
      // The seeds are baked tidy, so the drag is saved first; the Tidy up after it is then a change of its own.
      const saveNow = async () => {
        const resp = james.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/workflows/definitions`, { timeout: 60_000 });
        await james.getByTestId('definition-save').click();
        return (await (await resp).json()).data;
      };
      const draggedVersion = await saveNow();
      await james.keyboard.press('t');
      await james.getByText('Steps tidied').waitFor({ timeout: 10_000 });
      await james.waitForTimeout(SETTLE_MS);
      const tidied = await geometry(james, ROOT_SEL);
      editorClean('levy_case after Tidy up', tidied);
      const tidiedAt = rel(tidied, moved.id);
      // Undo by the keyboard: the toast's own Undo can sit under the toast of the save before it.
      await james.keyboard.press('ControlOrMeta+z');
      await james.waitForTimeout(SETTLE_MS);
      const undone = rel(await geometry(james, ROOT_SEL), moved.id);
      check(
        'levy_case: Tidy up moves the dragged step, and Undo puts it back where it was',
        !!undone && Math.abs(tidiedAt.y - dragged.y) > 4 && Math.abs(undone.x - dragged.x) <= 4 && Math.abs(undone.y - dragged.y) <= 4,
        { dragged, tidiedAt, undone },
      );
      await james.keyboard.press('t');
      await james.getByText('Steps tidied').first().waitFor({ timeout: 10_000 });
      await james.waitForTimeout(500);
      const tidiedVersion = await saveNow();
      // The seeds are baked with the same layout, so the tidied workflow is version 1 again, byte for byte.
      check(
        'levy_case: Save version saves the dragged layout as a new version, and Tidy up lays it out exactly as the baked seed',
        draggedVersion?.created === true && tidiedVersion?.version === 1 && tidiedVersion.created === false,
        { draggedVersion, tidiedVersion },
      );
      await james.screenshot({ path: join(EDITOR_SHOTS, 'levy_case-tidied-1280.png') });

      // A run's canvas: laid out, lines clear of steps, no Tidy up and no dragging.
      await fetch(`${agents}/v1/workflows/definitions/uc486_unplaced/publish-requests`, { method: 'POST', headers: H, body: '{}' });
      const started = await (
        await fetch(`${agents}/v1/runs`, { method: 'POST', headers: H, body: JSON.stringify({ workflowId: 'uc486_unplaced', input: { record: { name: 'Ana Example' } } }) })
      ).json();
      const runId = started.data?.runId ?? started.data?.id;
      await james.goto(`${consoleUrl}/workflows/runs/${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.locator('[data-testid=run-canvas] [data-testid=definition-node]').first().waitFor({ timeout: 120_000 });
      await james.waitForTimeout(SETTLE_MS);
      const rg = await geometry(james, '[data-testid=run-canvas]');
      clean('the run canvas', rg);
      const tidyOnRun = await james.locator('[data-testid=run-canvas] [data-testid=canvas-tidy]').count();
      const step = rg.steps[1];
      await james.mouse.move(step.x + step.w / 2, step.y + 12);
      await james.mouse.down();
      await james.mouse.move(step.x + step.w / 2, step.y + 150, { steps: 6 });
      await james.mouse.up();
      // A drag on a read-only canvas pans it, which moves every step alike; a step that dragged moves against the trigger.
      const after = await geometry(james, '[data-testid=run-canvas]');
      const still = after.steps.find((s) => s.id === step.id);
      const shift = still && Math.round(still.y - after.steps[0].y - (step.y - rg.steps[0].y));
      check('the run canvas offers no Tidy up and its steps do not drag', !!runId && tidyOnRun === 0 && Math.abs(shift) < 2, { runId, tidyOnRun, shift });
      await james.screenshot({ path: join(EDITOR_SHOTS, 'run-canvas-1280.png') });

      // 400 px and dark, after Fit to view.
      for (const scheme of ['light', 'dark']) {
        const narrow = await (await browser.newContext({ viewport: { width: 400, height: 860 }, colorScheme: scheme })).newPage();
        narrow.errors = [];
        narrow.on('pageerror', (e) => narrow.errors.push(e.message));
        await narrow.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await narrow.getByLabel('Email').fill(JAMES);
        await narrow.getByLabel('Password').fill(PASSWORD);
        await narrow
          .getByRole('button', { name: /^Sign in/ })
          .first()
          .click();
        await narrow.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await narrow.goto(`${consoleUrl}/workflows/definitions/levy_case`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await narrow.locator(`${ROOT_SEL} [data-testid=definition-node]`).first().waitFor({ timeout: 120_000 });
        await narrow.getByRole('button', { name: 'Fit to view' }).first().click();
        await narrow.waitForTimeout(SETTLE_MS);
        const ng = await geometry(narrow, ROOT_SEL);
        check(
          `levy_case at 400 px (${scheme}): Fit to view shows every step`,
          ng.steps.every((s) => s.x >= ng.canvas.x - 1 && s.x + s.w <= ng.canvas.x + ng.canvas.w + 1),
          ng.canvas,
        );
        await narrow.screenshot({ path: join(EDITOR_SHOTS, `levy_case-400-${scheme}.png`) });
        james.errors.push(...narrow.errors);
        await narrow.context().close();
      }
      mkdirSync(EDITOR_SHOTS, { recursive: true });
      writeFileSync(join(SHOTS, 'timings.json'), `${JSON.stringify(timings, null, 2)}\n`);
      const errors = [...james.errors];
      check('no page errors', errors.length === 0, errors.slice(0, 5));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
