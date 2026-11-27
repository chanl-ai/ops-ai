import type { CSSProperties } from 'react';

import { FigureFrame } from './parts';

type Compare = { options: { name: string; text?: string; rows: { label: string; value: string }[] }[]; pick?: string };

/**
 * Two or three options side by side, rows aligned across them, the recommended one marked. Stacks on a phone, each
 * option keeping its labels. Markdown: `<!-- site: compare pick="Option" caption="..." -->` above a list of
 * `**Option**: one line`, each with the same nested `**Label**: value` rows in the same order. For more than three
 * options or more than five rows, use a table.
 */
export function CompareFigure({ data, caption }: { data: string; caption?: string }) {
  const { options, pick } = JSON.parse(data) as Compare;
  const rows = Math.max(...options.map((o) => o.rows.length));
  const grid = { '--n': options.length, '--rows': rows + 2 } as CSSProperties;
  return (
    <FigureFrame caption={caption}>
      <ul className="ops-compare" style={grid}>
        {options.map((o) => (
          <li key={o.name} className={`ops-compare-option${o.name === pick ? ' ops-compare-pick' : ''}`}>
            <div className="ops-compare-head">
              <p className="ops-compare-name">{o.name}</p>
              {o.name === pick && <span className="ops-chip ops-chip-done">Recommended</span>}
            </div>
            <p className="ops-compare-text">{o.text ?? ''}</p>
            {o.rows.map((r) => (
              <dl key={r.label} className="ops-compare-row">
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </dl>
            ))}
          </li>
        ))}
      </ul>
    </FigureFrame>
  );
}
