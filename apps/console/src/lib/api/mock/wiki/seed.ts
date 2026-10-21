import type { WikiGate, WikiProvenance } from '@/lib/types/wiki';

/** Harbor & Pine's Wiki at seed time: 14 pages across four collections, two remembered by agents and two drifted. */
export interface PageSeed {
  id: string;
  title: string;
  collection: string;
  provenance: WikiProvenance;
  origin: string;
  version: number;
  verifiedDaysAgo: number | null;
  verifiedBy?: string;
  owner: string;
  editedDaysAgo: number;
  editedBy: string;
  citedBy: number;
  drift?: string;
  excerpt: string;
}

export const COLLECTIONS: { id: string; name: string; gate: WikiGate; audience: string; knowledgeBases: string[] }[] = [
  { id: 'col_lending', name: 'Lending policy', gate: 'team', audience: 'Lending Ops and Compliance', knowledgeBases: ['Lending policy'] },
  { id: 'col_fees', name: 'Fees and limits', gate: 'open', audience: 'Everyone at Harbor & Pine', knowledgeBases: ['Retail banking', 'Cards & disputes'] },
  { id: 'col_onboarding', name: 'Onboarding', gate: 'gated', audience: 'Onboarding, with Compliance approval per page', knowledgeBases: ['Compliance'] },
  { id: 'col_playbooks', name: 'Support playbooks', gate: 'team', audience: 'Retail Banking and Card Services', knowledgeBases: ['Retail banking', 'Cards & disputes', 'Fraud & payments'] },
];

export const PAGES: PageSeed[] = [
  { id: 'wp_hardship', title: 'Hardship deferral policy', collection: 'Lending policy', provenance: 'external', origin: 'SharePoint · Lending', version: 7, verifiedDaysAgo: 12, verifiedBy: 'Anika Singh', owner: 'Lending Ops', editedDaysAgo: 12, editedBy: 'Anika Singh', citedBy: 214, excerpt: 'A borrower in documented hardship may defer up to three monthly payments in any 12 months. Interest continues to accrue. The deferral is approved by a lending specialist and confirmed to the borrower in writing within two business days.' },
  { id: 'wp_payoff', title: 'Payoff statement requests', collection: 'Lending policy', provenance: 'external', origin: 'SharePoint · Lending', version: 4, verifiedDaysAgo: 30, verifiedBy: 'Daniel Brooks', owner: 'Lending Ops', editedDaysAgo: 3, editedBy: 'Sync', citedBy: 167, drift: 'The SharePoint page now says payoff quotes are valid for 10 days, not 15.', excerpt: 'Payoff statements are issued to the borrower of record or an authorised third party with written consent. A quote is valid for 15 calendar days from its issue date.' },
  { id: 'wp_address', title: 'Change of mailing address', collection: 'Lending policy', provenance: 'page', origin: 'Written in the Wiki', version: 2, verifiedDaysAgo: 60, verifiedBy: 'Anika Singh', owner: 'Lending Ops', editedDaysAgo: 60, editedBy: 'Anika Singh', citedBy: 88, excerpt: 'An address change needs the borrower confirmed by callback to the number on file. Changes requested by email alone are drafted and held for a person.' },
  { id: 'wp_jumbo', title: 'Jumbo mortgage underwriting', collection: 'Lending policy', provenance: 'file', origin: 'Underwriting manual 2026.pdf', version: 3, verifiedDaysAgo: 41, verifiedBy: 'Priya Shah', owner: 'Lending Ops', editedDaysAgo: 41, editedBy: 'Priya Shah', citedBy: 52, excerpt: 'Loans above $1,000,000 need a second underwriter and a full appraisal. Debt service ratios above 39% are declined without an exception from the credit committee.' },
  { id: 'wp_fee_schedule', title: 'Personal account fee schedule', collection: 'Fees and limits', provenance: 'file', origin: 'Fee schedule Oct 2026.pdf', version: 9, verifiedDaysAgo: 5, verifiedBy: 'Maya Okafor', owner: 'Retail Banking', editedDaysAgo: 5, editedBy: 'Maya Okafor', citedBy: 402, excerpt: 'Monthly account fee $16.95, waived with a $4,000 minimum daily balance. Interac e-Transfer free up to 30 a month, then $1.00 each.' },
  { id: 'wp_wire_limits', title: 'Wire transfer limits', collection: 'Fees and limits', provenance: 'external', origin: 'Confluence · Payments', version: 5, verifiedDaysAgo: 18, verifiedBy: 'Daniel Brooks', owner: 'Fraud Strategy', editedDaysAgo: 2, editedBy: 'Sync', citedBy: 133, drift: 'Confluence raised the same-day outbound limit for business accounts from $250,000 to $500,000.', excerpt: 'Same-day outbound wires are limited to $250,000 for business accounts and $50,000 for personal accounts. Larger wires need a callback and a second approver.' },
  { id: 'wp_atm_limits', title: 'Debit card and ATM limits', collection: 'Fees and limits', provenance: 'page', origin: 'Written in the Wiki', version: 3, verifiedDaysAgo: 22, verifiedBy: 'Maya Okafor', owner: 'Card Services', editedDaysAgo: 22, editedBy: 'Maya Okafor', citedBy: 97, excerpt: 'Daily ATM withdrawal limit $1,000; point-of-sale limit $5,000. A customer may request a temporary increase for 24 hours by phone.' },
  { id: 'wp_kyb_owners', title: 'Beneficial owner verification', collection: 'Onboarding', provenance: 'external', origin: 'SharePoint · Compliance', version: 6, verifiedDaysAgo: 9, verifiedBy: 'Priya Shah', owner: 'Onboarding', editedDaysAgo: 9, editedBy: 'Priya Shah', citedBy: 156, excerpt: 'Every owner holding 25% or more is verified against government ID and the corporate registry. A watchlist hit routes the application to Enhanced Due Diligence.' },
  { id: 'wp_edd', title: 'Enhanced due diligence triggers', collection: 'Onboarding', provenance: 'file', origin: 'AML procedures v12.docx', version: 12, verifiedDaysAgo: 14, verifiedBy: 'Priya Shah', owner: 'Compliance', editedDaysAgo: 14, editedBy: 'Priya Shah', citedBy: 71, excerpt: 'Enhanced due diligence applies to politically exposed persons, cash-intensive businesses and any owner in a high-risk jurisdiction list maintained by Compliance.' },
  { id: 'wp_kyb_remember', title: 'Registry lookups that time out', collection: 'Onboarding', provenance: 'remembered', origin: 'KYB Verifier', version: 1, verifiedDaysAgo: null, owner: 'Onboarding', editedDaysAgo: 1, editedBy: 'KYB Verifier', citedBy: 4, excerpt: 'When the provincial registry lookup times out twice, retry after 10 minutes and note the attempt on the case instead of marking the owner unverified.' },
  { id: 'wp_dispute_codes', title: 'Card dispute reason codes', collection: 'Support playbooks', provenance: 'external', origin: 'Zendesk · Guide', version: 8, verifiedDaysAgo: 7, verifiedBy: 'Maya Okafor', owner: 'Card Services', editedDaysAgo: 7, editedBy: 'Maya Okafor', citedBy: 288, excerpt: 'Match each dispute to one reason code: fraud, not received, not as described, duplicate, or credit not processed. Provisional credit applies to fraud and duplicate under $500.' },
  { id: 'wp_holiday_hours', title: 'Branch holiday hours', collection: 'Support playbooks', provenance: 'page', origin: 'Written in the Wiki', version: 4, verifiedDaysAgo: 3, verifiedBy: 'Maya Okafor', owner: 'Retail Banking', editedDaysAgo: 3, editedBy: 'Maya Okafor', citedBy: 64, excerpt: 'Branches close on statutory holidays. On Christmas Eve and New Year’s Eve they close at 2 pm local time.' },
  { id: 'wp_callback', title: 'Callback verification script', collection: 'Support playbooks', provenance: 'page', origin: 'Written in the Wiki', version: 2, verifiedDaysAgo: 95, verifiedBy: 'Daniel Brooks', owner: 'Fraud Strategy', editedDaysAgo: 95, editedBy: 'Daniel Brooks', citedBy: 39, excerpt: 'Call the number on file, never one given in the request. Confirm two of: date of birth, last deposit amount, account open date.' },
  { id: 'wp_concierge_remember', title: 'Customers asking for safe deposit boxes', collection: 'Support playbooks', provenance: 'remembered', origin: 'Branch Concierge', version: 1, verifiedDaysAgo: null, owner: 'Retail Banking', editedDaysAgo: 2, editedBy: 'Branch Concierge', citedBy: 11, excerpt: 'Safe deposit boxes are available at 14 branches. Book a branch appointment instead of quoting availability, which changes daily.' },
];

/** A page verified more than this many days ago needs verification again. */
export const VERIFY_EVERY_DAYS = 90;
