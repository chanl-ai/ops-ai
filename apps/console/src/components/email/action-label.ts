const LABELS: Record<string, string> = {
  send_reply: 'Reply to customer',
  get_transactions: 'Look up transactions',
  issue_provisional_credit: 'Issue provisional credit',
  place_card_block: 'Block the card',
  waive_fee: 'Waive a fee',
  update_address: 'Update address',
  get_loan_account: 'Look up the loan',
  apply_payment_deferral: 'Apply payment deferral',
  send_payoff_statement: 'Send payoff statement',
};

/** Human label for an action id. Unknown tool ids read as a sentence-case phrase. */
export const actionLabel = (action: string) => LABELS[action] ?? action.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
