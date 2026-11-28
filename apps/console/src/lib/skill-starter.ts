/**
 * The text a new skill starts with: a step the author picks a tool for, then a path on an `if` line with its `else:`.
 * Every line is the author's to rewrite. Lines with no tool join the step below them, so the first step is one line and
 * the starter runs as the steps it shows; the skill text reader's own test holds a copy of this text and reads it.
 */
export const WORKED_EXAMPLE = [
  'Greet them, ask for their order number and look the order up: type @ at the end of this line to pick the tool.',
  'if they want a refund:',
  '    Explain the refund policy and ask them to confirm.',
  'else:',
  '    Answer their question from what you found.',
].join('\n');
