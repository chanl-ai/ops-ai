import * as React from 'react';

// A reference such as NS-2026-GN-01187 or CHQ-2219: a digit and a hyphen or slash in one word. Browsers break lines
// after a hyphen or slash, which splits the reference across two lines. A longer token is left to wrap, so one token
// can never push a line wider than its box.
const REFERENCE = /^(?=\S*\d)(?=\S*[-/])\S{3,28}$/;

/** Text that wraps between words but never inside a reference: each reference-like token is kept on one line. */
export function WholeTokens({ text }: { text: string }) {
  const parts = text.split(/(\s+)/);
  if (!parts.some((p) => REFERENCE.test(p))) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) =>
        REFERENCE.test(p) ? (
          <span key={i} className="whitespace-nowrap">
            {p}
          </span>
        ) : (
          <React.Fragment key={i}>{p}</React.Fragment>
        )
      )}
    </>
  );
}
