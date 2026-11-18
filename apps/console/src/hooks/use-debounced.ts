'use client';

import * as React from 'react';

/** `value` after it has held still for `ms`: the text of a search box, so the server is asked once per pause. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
