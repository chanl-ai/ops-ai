/**
 * The generated SDK types a field loosely (`string` for an enum, `{ [key: string]: unknown }` for a nested object).
 * `Narrow` keeps the generated shape (names, which fields are optional or nullable) and swaps in the console's
 * precise type for the fields the generator cannot express.
 */
export type Narrow<Served, Over> = Omit<Served, keyof Over> & Over;
