// Sample documents for the c-159 preview: one knowledge base's documents as the simplified page would show them.
import type { ItemStatus } from '@/lib/types/knowledge';

export interface PreviewDoc {
  id: string;
  name: string;
  mime: string;
  kind: 'file' | 'text' | 'link';
  status: ItemStatus;
  version: number;
  updatedAt: string;
  citedBy: string[];
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

export const BASE = { name: 'Lending policy', description: 'Mortgage, hardship and fee rules the lending agents answer from.' };

export const DOCS: PreviewDoc[] = [
  { id: 'd1', name: 'Hardship policy 2026.pdf', mime: 'application/pdf', kind: 'file', status: 'indexed', version: 3, updatedAt: ago(60 * 26), citedBy: ['Mortgage Intake', 'Advisor’s Helper'] },
  { id: 'd2', name: 'Fee schedule.pdf', mime: 'application/pdf', kind: 'file', status: 'indexed', version: 1, updatedAt: ago(60 * 24 * 9), citedBy: ['Branch Concierge'] },
  { id: 'd3', name: 'Rate sheet (Oct).docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', kind: 'file', status: 'indexed', version: 2, updatedAt: ago(60 * 5), citedBy: [] },
  { id: 'd4', name: 'Deferral FAQ', mime: 'text/plain', kind: 'text', status: 'indexed', version: 1, updatedAt: ago(90), citedBy: ['Mortgage Intake'] },
  { id: 'd5', name: 'harborpine.example/mortgages/rates', mime: 'text/html', kind: 'link', status: 'failed', version: 1, updatedAt: ago(30), citedBy: [] },
];

/** Ingestion presets, moved off the add flow into the base's settings. */
export const PRESETS = [
  { id: 'standard', name: 'Standard', detail: 'Text and headings; scanned pages without a text layer are skipped.' },
  { id: 'tables', name: 'Tables and forms', detail: 'Keeps table rows together; slower to index.' },
  { id: 'scanned', name: 'Scanned documents', detail: 'Reads scanned pages with OCR; slowest.' },
];
