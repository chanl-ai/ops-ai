import type { CSSProperties } from 'react';

import { FigureFrame, PathNode } from './parts';

type Moment = { when: string; text: string; note?: string };

/**
 * What happens over minutes, hours or days: moments on one track, across on a wide page and down on a phone. Markdown:
 * `<!-- site: timeline caption="..." -->` above a list of `**When**: what happens` (three to six); a nested bullet is
 * a detail under that moment.
 */
export function TimelineFigure({ data, caption }: { data: string; caption?: string }) {
  const moments = JSON.parse(data) as Moment[];
  return (
    <FigureFrame caption={caption}>
      <ol className="ops-timeline" style={{ '--n': moments.length } as CSSProperties}>
        {moments.map((m, i) => (
          <li key={m.when} className="ops-moment">
            <PathNode n={i + 1} />
            <div className="ops-moment-body">
              <p className="ops-moment-when">{m.when}</p>
              <p className="ops-moment-text">{m.text}</p>
              {m.note && <p className="ops-moment-note">{m.note}</p>}
            </div>
          </li>
        ))}
      </ol>
    </FigureFrame>
  );
}
