import type {
  PromptAnalysis,
  PromptContext,
  PromptLintFinding,
  PromptSection,
  PromptSpec,
  PromptStreamEvent,
} from '@/lib/types/prompts';

import { ApiError } from '../../contract';
import type { PromptsApi } from '../../prompts-contract';
import { mode, respond } from '../runtime';
import { VARIABLES } from './seed';

export interface PromptsDeps {
  /** Every tool name in the catalog, to spot tools a prompt mentions but the agent was not granted. */
  toolNames: () => string[];
}

/** USD per million input tokens at list price; the AI gateway's price table in production. */
const PRICE_PER_M: Record<string, number> = { 'claude-haiku-4-5': 1, 'claude-sonnet-5': 3, 'claude-opus-5-5': 15 };
const TOO_LONG_TOKENS = 1800;
const VAR_RE = /(?<!\{)\{([a-z_]+(?:\.[a-z_]+)*)\}(?!\})/g;

const UNSURE_TEXT = { handoff: 'hand the case to a person and say why', ask: 'ask one clarifying question before you continue', decline: 'decline and explain what you cannot do' } as const;
const VERBOSITY = { brief: 'Keep replies under 120 words.', standard: 'Keep replies under 250 words.', detailed: 'Be thorough; cover every point the request raises.' } as const;
const FORMAT = { email: 'an email', json: 'JSON only, with no text around it', bullets: 'a bullet summary', memo: 'an internal memo', chat: 'a chat reply' } as const;

const bullets = (xs: string[]) => xs.filter((x) => x.trim()).map((x) => `- ${x.trim()}`).join('\n');
const numbered = (xs: string[]) => xs.filter((x) => x.trim()).map((x, i) => `${i + 1}. ${x.trim()}`).join('\n');
const para = (...xs: (string | false | undefined)[]) => xs.filter((x): x is string => !!x && !!x.trim()).join('\n\n');

/** "a fraud analyst's assistant" reads as a noun; "Drafts replies …" as a job, so it becomes "an agent that drafts replies …". */
const roleLine = (role: string) => {
  const r = role.trim().replace(/\.$/, '');
  if (!r) return 'You are an agent at Harbor & Pine Bank.';
  return /^(a|an|the)\b/i.test(r) ? `You are ${r} at Harbor & Pine Bank.` : `You are an agent at Harbor & Pine Bank that ${r.replace(/^./, (c) => c.toLowerCase())}.`;
};

/** The deterministic stand-in for the gateway model: the same spec always yields the same sections. */
function compose(spec: PromptSpec): PromptSection[] {
  const { purpose: p, behaviour: b, process: pr, toolsKnowledge: tk, compliance: c, output: o } = spec;
  const sections: PromptSection[] = [
    {
      id: 'purpose',
      title: 'Role and purpose',
      body: para(
        `${roleLine(p.role)}${p.serves.trim() ? ` You work for ${p.serves.trim().replace(/^./, (c) => c.toLowerCase())}.` : ''}`,
        p.goals.some((g) => g.trim()) && `Your goals:\n${bullets(p.goals)}`,
        p.outOfScope.some((g) => g.trim()) && `Out of scope:\n${bullets(p.outOfScope)}\nIf asked about any of these, say it is outside what you can help with.`,
      ),
    },
    {
      id: 'behaviour',
      title: 'Behaviour',
      body: para(
        `Tone: ${b.tone || 'professional'}. Write at a ${b.readingLevel || 'grade 8'} reading level${b.languages.length ? ` and reply in ${b.languages.join(' or ')}` : ''}. ${VERBOSITY[b.verbosity]}`,
        `When you are unsure, ${UNSURE_TEXT[b.whenUnsure]}.`,
        b.escalationTriggers.some((x) => x.trim()) && `Hand to a person when:\n${bullets(b.escalationTriggers)}`,
      ),
    },
    {
      id: 'process',
      title: 'Procedure',
      body: para(
        pr.steps.some((x) => x.trim()) && `Follow these steps in order:\n${numbered(pr.steps)}`,
        pr.decisionRules.some((x) => x.trim()) && `Decision rules:\n${bullets(pr.decisionRules)}`,
        pr.requiredChecks.some((x) => x.trim()) && `Before you act, check:\n${bullets(pr.requiredChecks)}`,
      ),
    },
    {
      id: 'tools',
      title: 'Tools and knowledge',
      body: para(
        tk.toolUse.some((t) => t.tool) && bullets(tk.toolUse.filter((t) => t.tool).map((t) => `Use ${t.tool} ${t.when.trim() ? `when ${t.when.trim().replace(/^when\s+/i, '')}` : 'when the task needs it'}.`)),
        tk.knowledge.length > 0 && `Search only these knowledge bases: ${tk.knowledge.join(', ')}.`,
        tk.citationRule.trim(),
        tk.neverWithTools.some((x) => x.trim()) && bullets(tk.neverWithTools.map((x) => (/^never\b/i.test(x.trim()) ? x : `Never ${x.trim().replace(/^./, (ch) => ch.toLowerCase())}`))),
      ),
    },
    {
      id: 'compliance',
      title: 'Compliance',
      body: para(
        c.disclosures.some((x) => x.trim()) && `Always include, word for word:\n${bullets(c.disclosures.map((x) => `"${x.trim()}"`))}`,
        c.forbiddenPhrases.some((x) => x.trim()) && `Never use these phrases:\n${bullets(c.forbiddenPhrases.map((x) => `"${x.trim()}"`))}`,
        c.piiHandling.trim() && `Personal data: ${c.piiHandling.trim()}`,
        c.regulatoryNotes.trim() && `Regulatory notes: ${c.regulatoryNotes.trim()}`,
      ),
    },
    {
      id: 'output',
      title: 'Output',
      body: para(
        `Write ${FORMAT[o.format]}.${o.structure.trim() ? ` ${o.structure.trim()}` : ''}`,
        o.variables.length > 0 && `Fill in: ${o.variables.map((v) => `{${v}}`).join(', ')}.`,
        o.examples.filter((e) => e.input.trim() && e.output.trim()).map((e, i) => `Example ${i + 1}\nInput: ${e.input.trim()}\nOutput: ${e.output.trim()}`).join('\n\n'),
      ),
    },
  ];
  return sections.filter((s) => s.body.trim());
}

/** "always cite the policy sections" and "never cite policy section" normalise to the same phrase. */
const normalise = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, ' ')
    .split(/\s+/)
    .filter((w) => w && !['the', 'a', 'an', 'any', 'every', 'to'].includes(w))
    .map((w) => w.replace(/s$/, ''))
    .join(' ');

const quote = (line: string) => line.trim().replace(/^[-*\d.\s]+/, '').replace(/\.$/, '');
const RULE_LINE = /^\s*(?:[-*]|\d+\.)?\s*(always|never)\s+(.+?)\.?\s*$/i;

function distance(a: string, b: string) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return d[a.length][b.length];
}

function analyze(sections: PromptSection[], ctx: PromptContext, toolNames: string[]): PromptAnalysis {
  const findings: PromptLintFinding[] = [];
  const keys = VARIABLES.map((v) => v.key);
  let n = 0;
  const add = (f: Omit<PromptLintFinding, 'id'>) => findings.push({ ...f, id: `lint_${++n}` });

  // Rules are compared across the whole prompt; the later of a conflicting pair is the one the fix removes.
  const rules: { verb: string; phrase: string; line: string; sectionId: string }[] = [];
  for (const s of sections)
    for (const line of s.body.split('\n')) {
      const m = RULE_LINE.exec(line);
      if (m) rules.push({ verb: m[1].toLowerCase(), phrase: normalise(m[2]), line, sectionId: s.id });
    }
  for (let i = 0; i < rules.length; i++)
    for (let j = i + 1; j < rules.length; j++) {
      const [a, b] = [rules[i], rules[j]];
      if (a.verb === b.verb || a.phrase !== b.phrase) continue;
      const sec = sections.find((s) => s.id === b.sectionId)!;
      add({
        rule: 'conflicting_rules',
        severity: 'error',
        sectionId: b.sectionId,
        message: `“${quote(a.line)}” conflicts with “${quote(b.line)}”.`,
        fix: { label: `Keep “${a.verb === 'always' ? 'Always' : 'Never'} …” and remove the other`, sectionId: b.sectionId, body: sec.body.split('\n').filter((l) => l !== b.line).join('\n') },
      });
    }

  for (const s of sections) {
    for (const m of s.body.matchAll(VAR_RE)) {
      if (keys.includes(m[1])) continue;
      const last = m[1].split('.').pop()!;
      const guess = keys.find((k) => k.endsWith(`.${last}`)) ?? [...keys].sort((x, y) => distance(x, m[1]) - distance(y, m[1]))[0];
      const close = guess && distance(guess, m[1]) <= Math.max(4, Math.floor(m[1].length / 2));
      add({
        rule: 'unknown_variable',
        severity: 'error',
        sectionId: s.id,
        message: `{${m[1]}} is not a variable the runtime can fill.`,
        fix: close ? { label: `Use {${guess}}`, sectionId: s.id, body: s.body.split(m[0]).join(`{${guess}}`) } : undefined,
      });
    }
    for (const t of toolNames) {
      if (ctx.grantedTools.includes(t) || !new RegExp(`\\b${t}\\b`).test(s.body)) continue;
      add({
        rule: 'tool_not_granted',
        severity: 'warning',
        sectionId: s.id,
        message: `Mentions ${t}, which this agent is not granted. The model cannot call it.`,
        fix: { label: `Remove lines that mention ${t}`, sectionId: s.id, body: s.body.split('\n').filter((l) => !l.includes(t)).join('\n') },
      });
    }
  }

  const all = sections.map((s) => s.body).join('\n');
  const cited = /\bcit(e|es|ing|ation)\b/i.test(all);
  if (ctx.collections.length && !cited) {
    const target = sections.find((s) => s.id === 'tools') ?? sections[sections.length - 1];
    add({
      rule: 'missing_citation_rule',
      severity: 'warning',
      sectionId: target?.id,
      message: 'The agent searches knowledge but nothing tells it to cite. Model Risk needs a citation for every policy statement.',
      fix: target && { label: 'Add the citation rule', sectionId: target.id, body: `${target.body}\n\nAlways cite the knowledge base and section behind every statement about a fee, limit, date or eligibility rule.` },
    });
  }

  const tokens = Math.ceil(all.length / 4);
  if (tokens > TOO_LONG_TOKENS) add({ rule: 'too_long', severity: 'warning', message: `${tokens.toLocaleString()} tokens. Prompts over ${TOO_LONG_TOKENS.toLocaleString()} tokens cost more per run and bury the rules; shorten a section with Rewrite.` });
  const price = PRICE_PER_M[ctx.model] ?? 3;
  return { tokens, costPer1kRunsUsd: Math.round(((tokens * price) / 1_000_000) * 1000 * 100) / 100, findings };
}

function rewrite(body: string, instruction: string): string {
  const i = instruction.toLowerCase();
  const lines = body.split('\n');
  if (/short|concise|trim|brief/.test(i)) {
    const keep = lines.filter((l) => l.trim());
    return keep.slice(0, Math.max(2, Math.ceil(keep.length / 2))).join('\n');
  }
  if (/bullet|list/.test(i))
    return body
      .split(/(?<=\.)\s+|\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => (/^[-*\d]/.test(l) ? l : `- ${l}`))
      .join('\n');
  if (/formal/.test(i)) return body.replace(/\bdon’t|don't\b/g, 'do not').replace(/\bcan’t|can't\b/g, 'cannot').replace(/\bwon’t|won't\b/g, 'will not').replace(/\bit’s|it's\b/g, 'it is');
  if (/french/.test(i)) return `${body}\n\nReply in French when {customer.preferred_language} is French.`;
  return `${body}\n${/^(always|never)\b/i.test(instruction.trim()) ? instruction.trim().replace(/\.?$/, '.') : `Also: ${instruction.trim().replace(/\.?$/, '.')}`}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Prompt tooling: the generator, rewrites and lint. Generation is deterministic and streams word by word. */
export function createPromptsMock(deps: PromptsDeps) {
  const api: PromptsApi = {
    variables: () => respond(() => VARIABLES),
    async *generate(spec: PromptSpec, ctx: PromptContext, signal?: AbortSignal): AsyncIterable<PromptStreamEvent> {
      const m = mode();
      await sleep(m === 'slow' ? 2500 : 400);
      if (m === 'error') throw new ApiError('The prompt builder could not reach the AI gateway. Nothing was generated; try again.', 503);
      if (!spec.purpose.role.trim()) throw new ApiError('Describe the role before generating.', 400);
      const sections = compose(spec);
      for (const s of sections) {
        if (signal?.aborted) return;
        yield { type: 'section', section: { id: s.id, title: s.title } };
        const words = s.body.split(/(?<=\s)/);
        for (let i = 0; i < words.length; i += 3) {
          if (signal?.aborted) return;
          await sleep(14);
          yield { type: 'delta', sectionId: s.id, text: words.slice(i, i + 3).join('') };
        }
      }
      yield { type: 'done', analysis: analyze(sections, ctx, deps.toolNames()) };
    },
    rewriteSection: (input) =>
      respond(() => {
        if (!input.instruction.trim()) throw new ApiError('Say how to rewrite the section.', 400);
        return { ...input.section, body: rewrite(input.section.body, input.instruction) };
      }),
    analyze: (sections, ctx) => respond(() => analyze(sections, ctx, deps.toolNames())),
  };
  return { api };
}
