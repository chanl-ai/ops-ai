import type { EmailWorkflowConfig } from '@/lib/types/cases';

/** Seed configuration for the two email intake workflows. Only the mock layer reads this file. */

export const QUEUES = ['Card disputes', 'Lending servicing', 'Account maintenance'];
export const APPROVER_GROUPS = ['Card Disputes', 'Card Services Leads', 'Lending Servicing', 'Lending Servicing Leads', 'Account Maintenance'];
export const ASSIGNEES = ['James Richardson', 'Maya Okafor', 'Anika Singh', 'Daniel Brooks', 'Priya Shah'];

export const CARD_INBOX_CONFIG: EmailWorkflowConfig = {
  confidenceThreshold: 0.7,
  fallbackQueue: 'Account maintenance',
  intents: [
    {
      id: 'dispute_charge',
      name: 'Dispute a card charge',
      description: 'Customer does not recognise or disagrees with a card transaction.',
      examples: [
        'I see a charge of $412.18 from TRVL*BOOKINGS on my card ending 4471 that I did not make.',
        'I was charged twice for the same order at Lakeside Furniture, please refund one of them.',
        'The merchant never delivered my order but the charge for $89.00 is still on my statement.',
      ],
      fields: [
        { key: 'card_last4', label: 'Card (last 4)', required: true },
        { key: 'merchant', label: 'Merchant', required: true },
        { key: 'amount', label: 'Amount', required: true },
        { key: 'transaction_date', label: 'Transaction date', required: false },
      ],
      actions: ['get_transactions', 'issue_provisional_credit', 'send_reply'],
    },
    {
      id: 'lost_stolen',
      name: 'Lost or stolen card',
      description: 'Card is lost, stolen or the customer suspects it was compromised.',
      examples: [
        'My wallet was stolen this morning and my credit card was in it. Please block it.',
        'I think my card details were skimmed at a gas station, there are charges I do not recognise.',
      ],
      fields: [
        { key: 'card_last4', label: 'Card (last 4)', required: true },
        { key: 'last_known_use', label: 'Last known use', required: false },
      ],
      actions: ['place_card_block', 'send_reply'],
    },
    {
      id: 'fee_refund',
      name: 'Fee refund request',
      description: 'Customer asks for an annual, late or foreign-transaction fee to be refunded.',
      examples: [
        'I was charged a $39 late fee but the payment went through on the due date.',
        'Can you waive the annual fee on my card? I have been a customer for 12 years.',
        'Why was I charged a foreign transaction fee on a purchase in Canadian dollars?',
      ],
      fields: [
        { key: 'fee_type', label: 'Fee type', required: true },
        { key: 'amount', label: 'Amount', required: true },
      ],
      actions: ['waive_fee', 'send_reply'],
    },
    {
      id: 'address_change',
      name: 'Change of address',
      description: 'Customer wants to update their mailing or statement address.',
      examples: [
        'I moved last month, please update my address to 88 Harbour Street, Unit 1204.',
        'Please send my statements to my new address, I have attached a utility bill.',
      ],
      fields: [
        { key: 'new_address', label: 'New address', required: true },
        { key: 'effective_date', label: 'Effective date', required: false },
      ],
      actions: ['update_address', 'send_reply'],
    },
  ],
  routes: [
    { intentId: 'dispute_charge', queue: 'Card disputes', priority: 'high', slaHours: 24, businessHours: true },
    { intentId: 'lost_stolen', queue: 'Card disputes', priority: 'urgent', slaHours: 2, businessHours: false },
    { intentId: 'fee_refund', queue: 'Account maintenance', priority: 'normal', slaHours: 48, businessHours: true },
    { intentId: 'address_change', queue: 'Account maintenance', priority: 'low', slaHours: 72, businessHours: true },
  ],
  approvals: [
    { id: 'ap_credit', action: 'issue_provisional_credit', label: 'Issue provisional credit', kind: 'tool', approverGroup: 'Card Disputes', fourEyes: true, autoApproveBelow: 50 },
    { id: 'ap_waive', action: 'waive_fee', label: 'Waive a fee', kind: 'tool', approverGroup: 'Card Services Leads', fourEyes: false, autoApproveBelow: 25 },
    { id: 'ap_address', action: 'update_address', label: 'Update address', kind: 'tool', approverGroup: 'Account Maintenance', fourEyes: false, autoApproveBelow: null },
    { id: 'ap_reply', action: 'send_reply', label: 'Send reply to customer', kind: 'reply', approverGroup: 'Card Disputes', fourEyes: false, autoApproveBelow: null },
  ],
};

export const LENDING_INBOX_CONFIG: EmailWorkflowConfig = {
  confidenceThreshold: 0.72,
  fallbackQueue: 'Lending servicing',
  intents: [
    {
      id: 'payment_deferral',
      name: 'Payment deferral or hardship',
      description: 'Borrower asks to skip, defer or reduce loan payments because of hardship.',
      examples: [
        'I lost my job last month and cannot make my mortgage payment on the 1st. Can I defer it?',
        'Due to medical bills I need to reduce my car loan payments for three months.',
        'Is there a hardship program? I will be on unpaid leave until March.',
      ],
      fields: [
        { key: 'loan_number', label: 'Loan number', required: true },
        { key: 'months', label: 'Months requested', required: false },
        { key: 'reason', label: 'Reason', required: true },
      ],
      actions: ['get_loan_account', 'apply_payment_deferral', 'send_reply'],
    },
    {
      id: 'payoff_statement',
      name: 'Payoff statement request',
      description: 'Borrower or their lawyer requests a payoff amount as of a date.',
      examples: [
        'Please send a payoff statement for loan 7700-31842 good through November 15.',
        'We are acting for the vendor in the sale of 14 Elm Crescent and need a mortgage payoff figure.',
      ],
      fields: [
        { key: 'loan_number', label: 'Loan number', required: true },
        { key: 'payoff_date', label: 'Payoff date', required: true },
      ],
      actions: ['send_payoff_statement', 'send_reply'],
    },
    {
      id: 'address_change',
      name: 'Change of address',
      description: 'Borrower wants to update their mailing address.',
      examples: ['We have moved, please update the address on our mortgage to 2 Birchwood Lane.', 'New mailing address attached, please update all my loan accounts.'],
      fields: [{ key: 'new_address', label: 'New address', required: true }],
      actions: ['update_address', 'send_reply'],
    },
  ],
  routes: [
    { intentId: 'payment_deferral', queue: 'Lending servicing', priority: 'high', slaHours: 24, businessHours: true },
    { intentId: 'payoff_statement', queue: 'Lending servicing', priority: 'normal', slaHours: 48, businessHours: true },
    { intentId: 'address_change', queue: 'Account maintenance', priority: 'low', slaHours: 72, businessHours: true },
  ],
  approvals: [
    { id: 'ap_defer', action: 'apply_payment_deferral', label: 'Apply payment deferral', kind: 'tool', approverGroup: 'Lending Servicing Leads', fourEyes: true, autoApproveBelow: null },
    { id: 'ap_address_l', action: 'update_address', label: 'Update address', kind: 'tool', approverGroup: 'Account Maintenance', fourEyes: false, autoApproveBelow: null },
    { id: 'ap_reply_l', action: 'send_reply', label: 'Send reply to customer', kind: 'reply', approverGroup: 'Lending Servicing', fourEyes: false, autoApproveBelow: null },
  ],
};

export const EMAIL_CONFIGS: Record<string, EmailWorkflowConfig> = {
  wf_card_inbox: CARD_INBOX_CONFIG,
  wf_lending_inbox: LENDING_INBOX_CONFIG,
};

export const MAILBOXES: Record<string, string> = {
  wf_card_inbox: 'cardservices@northfieldbank.com',
  wf_lending_inbox: 'lendingservicing@northfieldbank.com',
};
