type Params = Record<string, unknown>;

/** Drops a cleared setting rather than storing an empty value the schema may refuse. */
export const without = (p: Params, key: string, value: unknown): Params => {
  const next = { ...p };
  if (value === undefined || value === '') delete next[key];
  else next[key] = value;
  return next;
};
