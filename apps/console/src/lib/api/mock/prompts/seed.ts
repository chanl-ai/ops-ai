import type { PromptVariable } from '@/lib/types/prompts';

export const VARIABLES: PromptVariable[] = [
  { key: 'customer.first_name', label: 'Customer first name', example: 'Priya', source: 'Case → customer record' },
  { key: 'customer.last_name', label: 'Customer last name', example: 'Raman', source: 'Case → customer record' },
  { key: 'customer.preferred_language', label: 'Preferred language', example: 'French', source: 'Customer record' },
  { key: 'account.masked_number', label: 'Account number, masked', example: '****2231', source: 'Case → account' },
  { key: 'case.id', label: 'Case id', example: 'C-20931', source: 'Case' },
  { key: 'case.queue', label: 'Queue', example: 'Lending servicing', source: 'Case' },
  { key: 'case.sla_due', label: 'SLA due', example: 'Oct 8, 4:00 PM', source: 'Case' },
  { key: 'staff.name', label: 'Staff member', example: 'Sam Ortiz', source: 'Signed-in user' },
  { key: 'agent.name', label: 'Agent name', example: 'Reply Drafter', source: 'Agent' },
  { key: 'today', label: 'Today’s date', example: '2026-10-06', source: 'Runtime' },
];
