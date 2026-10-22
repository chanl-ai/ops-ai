import type { OptionSource } from '@/hooks/options-queries';
import type { StartForm } from '@/lib/types/engine';

/** Sample data for the start-run design preview (c-466): the start forms the server declares, and the team's files. */

export const NOTICE = { fileId: 'fil_court_order_notice', name: 'court-order-notice.pdf' };

const files = [
  { id: NOTICE.fileId, label: NOTICE.name, hint: 'Email attachment · 2 KB' },
  { id: 'fil_statement', label: 'account-statement-october.pdf', hint: 'Email attachment · 41 KB' },
  { id: 'fil_handbook', label: 'levy-and-garnishment-procedures.md', hint: 'Knowledge source · 6 KB' },
];

const pageOf = (rows: { id: string; label: string; hint?: string }[]): OptionSource['fetch'] => async ({ search, ids }) => ({
  data: rows.filter((r) => (ids?.length ? ids.includes(r.id) : !search || r.label.toLowerCase().includes(search.toLowerCase()))),
  nextCursor: null,
});

export const sampleFiles: OptionSource = { key: 'preview-start-files', fetch: pageOf(files) };

/** What Files offers to start with a file: email triggers and forms with a file field, never a sub-workflow. */
export const sampleFileWorkflows: OptionSource = {
  key: 'preview-start-file-workflows',
  fetch: pageOf([
    { id: 'levy_mail_intake', label: 'Court order notices by email', hint: 'Starts from an email' },
    { id: 'dispute_evidence', label: 'Card dispute with evidence', hint: 'Starts from a form' },
  ]),
};

/** The Email received trigger's start form, as `ops_engine.node_types.TEST_EMAIL_FORM` declares it. */
export const emailStart: StartForm = {
  kind: 'email',
  title: 'Send a test email',
  action: 'Send test email',
  via: 'test email',
  takesFiles: true,
  schema: {
    type: 'object',
    required: ['from'],
    properties: {
      from: { type: 'string', format: 'email', title: 'From', examples: ['clerk@county-court.example'] },
      subject: { type: 'string', title: 'Subject', examples: ['Notice of levy, case 2026-CV-1182'] },
      body: { type: 'string', title: 'Body', 'x-widget': 'textarea', examples: ['Please find the notice attached.'] },
      attachments: {
        type: 'array',
        title: 'Attachments',
        description: 'Upload files or pick ones already in Files; each reaches the workflow as a mailbox attachment would.',
        items: { type: 'object', format: 'file', properties: { fileId: { type: 'string' }, name: { type: 'string' } }, required: ['fileId'] },
      },
    },
  },
};

/** A Request trigger's start form: its input schema, with the evidence as a file field. */
export const formStart: StartForm = {
  kind: 'form',
  title: 'Start a run',
  action: 'Start run',
  via: 'form',
  takesFiles: true,
  schema: {
    type: 'object',
    required: ['cardholder', 'evidence'],
    properties: {
      cardholder: { type: 'string', title: 'Cardholder', examples: ['Jordan Whitfield'] },
      cardType: { type: 'string', title: 'Card type', oneOf: [{ const: 'debit', title: 'Debit card' }, { const: 'credit', title: 'Credit card' }] },
      evidence: { type: 'string', title: 'Evidence', format: 'file', description: 'The receipt or letter the cardholder sent.' },
      reason: { type: 'string', title: 'What happened', 'x-widget': 'textarea' },
    },
  },
};
