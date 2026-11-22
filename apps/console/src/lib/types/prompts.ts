/** A value the runtime fills into instructions, written `{customer.first_name}`. */
export interface PromptVariable {
  key: string;
  label: string;
  example: string;
  /** Where the runtime reads it from. */
  source: string;
}

