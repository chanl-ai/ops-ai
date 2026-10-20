import type { EvalCheck } from '@/lib/types/evals';
import type { SkillCitation, SkillSectionKey, SkillStart } from '@/lib/types/skills';

import { DOCUMENTS, SKILL_SEEDS, TEMPLATES } from './seed';

/**
 * What the mock "model" drafts. A real backend sends the start material and scope to the drafting alias through
 * the AI gateway; here each start resolves to a topic pack, so the same input always drafts the same skill.
 */
export interface Pack {
  name: string;
  useWhen: string;
  sections: Record<SkillSectionKey, string>;
  tools: string[];
  knowledgeBases: string[];
  guardrails: string[];
  tests: { name: string; input: string; checks: EvalCheck[] }[];
  matchTerms: string[];
}

export const SECTION_TITLE: Record<SkillSectionKey, string> = { steps: 'Steps', rules: 'Rules', examples: 'Examples', output_format: 'Output format' };
const ORDER: SkillSectionKey[] = ['steps', 'rules', 'examples', 'output_format'];

/** Splits a skill body into its four sections; text before the first heading goes to Steps. */
export function splitSections(instructions: string): Record<SkillSectionKey, string> {
  const out: Record<SkillSectionKey, string> = { steps: '', rules: '', examples: '', output_format: '' };
  let cur: SkillSectionKey = 'steps';
  for (const line of instructions.split('\n')) {
    const h = line.match(/^##\s+(.+)$/);
    const key = h && ORDER.find((k) => SECTION_TITLE[k].toLowerCase() === h[1].trim().toLowerCase());
    if (key) cur = key;
    else out[cur] += `${line}\n`;
  }
  for (const k of ORDER) out[k] = out[k].trim();
  return out;
}

export const joinSections = (s: Record<SkillSectionKey, string>) => ORDER.map((k) => `## ${SECTION_TITLE[k]}\n${s[k].trim()}`).join('\n\n');

const fromSeed = (id: string): Pack => {
  const s = SKILL_SEEDS.find((x) => x.id === id)!;
  return { name: s.name, useWhen: s.useWhen, sections: splitSections(s.instructions), tools: s.tools, knowledgeBases: s.knowledgeBases, guardrails: s.guardrails, tests: s.tests.map((t) => ({ name: t.name, input: t.input, checks: t.checks })), matchTerms: s.matchTerms };
};

const TEMPLATE_PACKS: Record<string, Pack> = {
  tpl_email_reply: {
    name: 'Customer email reply',
    useWhen: 'Use when a customer email asks a question about their account or a product and needs a written answer from policy and account data.',
    sections: {
      steps: '1. Read the email thread with `get_thread`.\n2. Find the customer with `get_customer_profile`.\n3. Search the knowledge base for the policy that answers the question.\n4. Draft the reply with `send_reply` for an approver.',
      rules: '- Answer only what was asked.\n- Cite the policy section in the case notes, not in the reply.\n- Never include a full account number.',
      examples: '> "What is the fee for a replacement card?"\n\nAnswer from the fee schedule, $15, and how to order one.',
      output_format: 'Reply under 150 words: answer, what to do next, sign-off.',
    },
    tools: ['get_thread', 'get_customer_profile', 'search_knowledge', 'send_reply'],
    knowledgeBases: ['Retail banking'],
    guardrails: ['Every reply waits for an approver.'],
    tests: [
      { name: 'Fee question', input: 'What is the fee for a replacement debit card?', checks: [{ type: 'calls_tool', tool: 'search_knowledge' }, { type: 'reply_not_contains', text: 'account number' }] },
      { name: 'Two questions in one email', input: 'Can I raise my e-transfer limit, and how long does it take?', checks: [{ type: 'calls_tool', tool: 'get_customer_profile' }] },
    ],
    matchTerms: ['question', 'email', 'how do i', 'what is'],
  },
  tpl_extraction: {
    name: 'Document field extraction',
    useWhen: 'Use when a message or attached document must be turned into named fields, such as an application, a statement or an identity document.',
    sections: {
      steps: '1. Find the document with `search_documents`.\n2. Read it with `get_document`.\n3. Extract each field in the output format; leave a field empty when it is not in the document.\n4. List fields that need a person to confirm.',
      rules: '- Never guess a value that is not in the document.\n- Dates in yyyy-mm-dd.\n- Mask government ID numbers except the last 3 digits.',
      examples: '> Mortgage commitment, 14 pages\n\n`{ "borrower": "Marcus Webb", "amount": 612000, "rate": 5.24, "signed": "2021-04-02" }`',
      output_format: 'JSON object with the fields listed in the step, plus `needsReview: string[]`.',
    },
    tools: ['search_documents', 'get_document'],
    knowledgeBases: ['Lending policy'],
    guardrails: ['Mask government ID numbers in every output.'],
    tests: [{ name: 'Commitment letter', input: 'Extract the borrower, amount and rate from the mortgage commitment for customer 88213.', checks: [{ type: 'calls_tool', tool: 'get_document' }, { type: 'reply_contains', text: 'amount' }] }],
    matchTerms: ['extract', 'fields', 'document'],
  },
  tpl_policy_qa: {
    name: 'Policy question answering',
    useWhen: 'Use when a staff member asks what the bank’s policy or procedure says about a situation.',
    sections: {
      steps: '1. Search the knowledge bases in scope with `search_knowledge`.\n2. Pick the passage with the latest effective date.\n3. Answer in two sentences and cite the section.',
      rules: '- Always cite the document, section and version.\n- If two passages conflict, say so and cite both.\n- Say "I could not find this" rather than answer from memory.',
      examples: '> "How many deferrals can a mortgage customer have in 24 months?"\n\nUp to three months in 24 (Hardship policy v7.2 §3.1).',
      output_format: 'Answer, then "Source:" with document, section and version.',
    },
    tools: ['search_knowledge'],
    knowledgeBases: ['Lending policy', 'Compliance'],
    guardrails: ['Never answer without a citation.'],
    tests: [{ name: 'Deferral limit', input: 'How many deferrals can a mortgage customer have in 24 months?', checks: [{ type: 'cites', source: 'Lending policy', section: '§3.1' }] }],
    matchTerms: ['policy', 'procedure', 'what does', 'allowed'],
  },
  tpl_triage: {
    name: 'Inbound request triage',
    useWhen: 'Use when a new request arrives and needs to be classified, have its facts gathered and be routed to the right queue.',
    sections: {
      steps: '1. Classify the request against the intents in the workflow.\n2. Gather the account facts with `get_customer_profile`.\n3. Route to the queue for the intent with the facts in the case note.',
      rules: '- Below 0.75 confidence, route to manual handling.\n- Never act on a request; only route it.',
      examples: '> "My card was stolen last night."\n\nIntent lost or stolen card, priority high, queue Card Services.',
      output_format: 'Case note: intent, confidence, facts, queue.',
    },
    tools: ['get_customer_profile'],
    knowledgeBases: ['Retail banking'],
    guardrails: ['Route below 0.75 confidence to manual handling.'],
    tests: [{ name: 'Stolen card', input: 'My card was stolen last night, please help.', checks: [{ type: 'reply_contains', text: 'queue' }] }],
    matchTerms: ['triage', 'route', 'classify'],
  },
  tpl_memo: fromSeed('sk_fee'),
};
TEMPLATE_PACKS.tpl_memo = { ...TEMPLATE_PACKS.tpl_memo, name: 'Approval decision memo' };

const TOPIC: Record<string, string> = { hardship: 'sk_hardship', payoff: 'sk_payoff', address: 'sk_address', dispute: 'sk_dispute', wire: 'sk_wire', kyc: 'sk_kyc', complaint: 'sk_complaint', fee: 'sk_fee' };
const TOPIC_WORDS: [string, RegExp][] = [
  ['hardship', /hardship|defer|deferral|skip|can.?t pay|lost (my|their) job|laid off/i],
  ['payoff', /payoff|pay ?out|discharge/i],
  ['address', /address|moved|relocat/i],
  ['dispute', /dispute|charge ?back|duplicate|not received/i],
  ['wire', /wire|hold/i],
  ['kyc', /kyc|know your|refresh|beneficial owner/i],
  ['complaint', /complain/i],
  ['fee', /fee|waive|waiver/i],
];

export const topicOf = (text: string) => TOPIC_WORDS.find(([, re]) => re.test(text))?.[0];

const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A pack written from free text when no topic matches. */
function described(text: string): Pack {
  const words = text.replace(/[^\w\s'-]/g, '').split(/\s+/).filter(Boolean);
  const asked = text.match(/(?:asks? for|requests?|wants?|needs?)\s+(?:a |an |the )?([^,.;]+)/i)?.[1];
  const name = asked ? `${titleCase(asked.split(/\s+/).slice(0, 5).join(' ').toLowerCase())} request` : titleCase(words.slice(0, 5).join(' ').toLowerCase()) || 'New procedure';
  return {
    name,
    useWhen: `Use when ${text.trim().replace(/\.$/, '').replace(/^(when|use when)\s+/i, '').toLowerCase()}.`,
    sections: {
      steps: `1. Read the request and identify what is being asked.\n2. Gather the facts the request needs from the tools in scope.\n3. ${text.trim().replace(/\.$/, '')}.\n4. Record what you did and why in the case note.`,
      rules: '- Stop and hand off to a person when the facts do not support an answer.\n- Never act on another customer’s record.',
      examples: `> A request matching: "${text.trim().slice(0, 80)}"\n\nOutcome recorded in the case note.`,
      output_format: 'Case note with what was asked, the facts found and the outcome.',
    },
    tools: ['search_knowledge'],
    knowledgeBases: [],
    guardrails: [],
    tests: [{ name: 'Typical request', input: text.trim().slice(0, 140), checks: [{ type: 'calls_tool', tool: 'search_knowledge' }] }],
    matchTerms: words.filter((w) => w.length > 5).slice(0, 4).map((w) => w.toLowerCase()),
  };
}

export interface PastWorkItem {
  id: string;
  kind: 'case' | 'run' | 'chat';
  title: string;
  detail: string;
  group: string;
  at: string;
}

/** Resolves the start material to a pack and the citations the draft carries back to it. */
export function packFor(start: SkillStart, pastWork: PastWorkItem[]): { pack: Pack; citations: Omit<SkillCitation, 'id'>[]; status: string } {
  if (start.kind === 'template') {
    const t = TEMPLATES.find((x) => x.id === start.templateId);
    const topic = start.text ? topicOf(start.text) : undefined;
    const pack = topic ? fromSeed(TOPIC[topic]) : (TEMPLATE_PACKS[start.templateId] ?? described(start.text || 'Handle the request'));
    return { pack, citations: [{ kind: 'template', label: `${t?.name ?? 'Template'} template`, section: 'output_format' }], status: `Drafting from the ${t?.name ?? ''} template…` };
  }
  if (start.kind === 'document') {
    const docs = DOCUMENTS.filter((d) => start.documentIds.includes(d.id));
    const topic = docs[0]?.topic;
    const pack = topic ? fromSeed(TOPIC[topic]) : described('Follow the uploaded procedure');
    const citations: Omit<SkillCitation, 'id'>[] = [
      ...docs.map((d) => ({ kind: 'document' as const, label: d.title, detail: `${d.kb} · ${d.detail}`, section: 'steps' as const })),
      ...docs.map((d) => ({ kind: 'document' as const, label: `${d.title} · rules`, detail: d.kb, section: 'rules' as const })),
      ...start.fileIds.map((f, i) => ({ kind: 'document' as const, label: `Uploaded SOP ${i + 1}`, detail: f, section: 'steps' as const, href: `/files?file=${f}` })),
    ];
    return { pack, citations, status: `Reading ${docs.length + start.fileIds.length === 1 ? 'the document' : `${docs.length + start.fileIds.length} documents`}…` };
  }
  if (start.kind === 'past_work') {
    const items = pastWork.filter((p) => start.itemIds.includes(p.id));
    const topic = topicOf(items.map((i) => `${i.title} ${i.group}`).join(' '));
    const pack = topic ? fromSeed(TOPIC[topic]) : described(items[0]?.title ?? 'Handle the request');
    const citations: Omit<SkillCitation, 'id'>[] = items.slice(0, 6).map((i) => ({ kind: i.kind, label: i.title, detail: `${i.id} · ${i.detail}`, section: 'examples', href: i.kind === 'case' ? `/cases/${i.id}` : i.kind === 'chat' ? `/chat/${i.id}` : undefined }));
    if (items.length > 6) citations.push({ kind: items[0].kind, label: `${items.length - 6} more`, section: 'examples' });
    citations.push({ kind: 'description', label: `Common steps across ${items.length} ${items.length === 1 ? 'item' : 'items'}`, section: 'steps' });
    return { pack, citations, status: `Reading ${items.length} past ${items.length === 1 ? 'item' : 'items'}…` };
  }
  const topic = topicOf(start.text);
  return { pack: topic ? fromSeed(TOPIC[topic]) : described(start.text), citations: [{ kind: 'description', label: 'Your description', detail: start.text.slice(0, 120), section: 'use_when' }], status: 'Drafting from your description…' };
}

/** Applies a rewrite instruction to a section. Deterministic so a reviewer can reproduce it. */
export function rewrite(section: SkillSectionKey, current: string, instruction: string): string {
  const i = instruction.toLowerCase();
  const lines = current.split('\n').filter((l) => l.trim());
  if (/short|concise|trim|fewer/.test(i)) return lines.slice(0, Math.max(2, Math.ceil(lines.length / 2))).join('\n');
  if (/example/.test(i) && section === 'examples') return `${current.trim()}\n\n> "Can I change the date my payment comes out?"\n\nNot a hardship request: route to Lending Servicing.`;
  if (/plain|simple|reading/.test(i)) return lines.map((l) => l.replace(/ with `[^`]+`/g, '').replace(/\s+/g, ' ')).join('\n');
  const numbered = lines.length && /^\d+\./.test(lines[0]);
  const topic = instruction.trim().replace(/\.$/, '').match(/^add (?:a |an )?(?:rule|step|check)s? (?:about|for|on|covering) (.+)$/i)?.[1];
  const text = topic ? (section === 'steps' ? `Check ${topic} before acting, and hand off to a person when it does not fit the procedure` : `${titleCase(topic)}: confirm the procedure covers it before acting; hand off to a person when it does not`) : titleCase(instruction.trim().replace(/\.$/, ''));
  const bullet = numbered ? `${lines.length + 1}. ${text}.` : `- ${text}.`;
  return [...lines, bullet].join('\n');
}
