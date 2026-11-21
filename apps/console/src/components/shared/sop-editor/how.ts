/** What each condition label means, in one line: the label's tooltip and the cue bar above the text say the same. */
export const HOW_SAYS = {
  checked: 'Checked: tested in code on what the tool above returns, so this path always holds.',
  agent: "Judged: a separate model checks this against the tool's result when it arrives; if it says no, the step takes its 'if not'.",
} as const;
