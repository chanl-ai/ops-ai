/**
 * A gate's rule (`amount > 50,000 AND payee.age < 72h`) read as words a person uses ("amount is over 50,000 and payee
 * age is under 72h"). Field paths become words (`payee.age` is "payee age", `nameMatch` is "name match"), operators
 * become phrases, and the joining AND, OR and NOT become lower case. Anything not recognised is kept as written.
 */
const OPERATORS: [RegExp, string][] = [
  [/\s*>=\s*/g, ' is at least '],
  [/\s*<=\s*/g, ' is at most '],
  [/\s*!=\s*/g, ' is not '],
  [/\s*==?\s*/g, ' is '],
  [/\s*>\s*/g, ' is over '],
  [/\s*<\s*/g, ' is under '],
  [/\s+NOT IN\s+/g, ' is not in '],
  [/\s+IN\s+/g, ' is in '],
  [/\s+AND\s+/g, ' and '],
  [/\s+OR\s+/g, ' or '],
  [/\bNOT\s+/g, 'not '],
];

function field(token: string): string {
  // A number or a quantity (50,000, 0.75, 72h) stays as written; a name is split on dots, underscores and capitals.
  if (/^[\d.,]+[a-z%]*$/i.test(token)) return token;
  return token
    .replace(/[._]/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .toLowerCase();
}

export function conditionInWords(rule: string): string {
  let out = rule.trim();
  for (const [op, words] of OPERATORS) out = out.replace(op, words);
  return out
    .split(/(\s+)/)
    .map((part) => (/^\s+$/.test(part) ? part : field(part)))
    .join('');
}
