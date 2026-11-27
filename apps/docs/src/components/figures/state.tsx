import { CornerDownRight } from 'lucide-react';

import { FigureFrame } from './parts';

type State = { name: string; text?: string; next: { to: string; when: string }[]; tone?: 'done' | 'stop' };

/**
 * A lifecycle: the states something passes through, each with what moves it on, and the states it can end in set
 * apart below. Markdown: `<!-- site: state caption="..." -->` above a list of `**State**: what it means`, each nested
 * bullet a transition `**Next state**: what triggers it`. A state with no transitions is an end; one named failed,
 * stuck, declined, rejected, cancelled or expired is drawn as a stop, the rest as a finish.
 */
export function StateFigure({ data, caption }: { data: string; caption?: string }) {
  const states = JSON.parse(data) as State[];
  const moving = states.filter((s) => !s.tone);
  const ends = states.filter((s) => s.tone);
  return (
    <FigureFrame caption={caption}>
      <div className="ops-states">
        <ol className="ops-states-flow">
          {moving.map((s) => (
            <li key={s.name} className="ops-state">
              <p className="ops-state-name">{s.name}</p>
              {s.text && <p className="ops-state-text">{s.text}</p>}
              <ul className="ops-state-next">
                {s.next.map((t) => (
                  <li key={t.to + t.when}>
                    <CornerDownRight aria-hidden className="ops-state-arrow" strokeWidth={1.5} />
                    <span>
                      <span className="ops-state-when">{t.when}</span> <span className="ops-sr">moves to </span>
                      <span className={`ops-chip ops-chip-${states.find((x) => x.name === t.to)?.tone ?? 'step'}`}>{t.to}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
        {ends.length > 0 && (
          <div className="ops-states-ends">
            <p className="ops-states-ends-label">Ends</p>
            <ul>
              {ends.map((s) => (
                <li key={s.name} className={`ops-state ops-state-end ops-state-${s.tone}`}>
                  <p className="ops-state-name">{s.name}</p>
                  {s.text && <p className="ops-state-text">{s.text}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </FigureFrame>
  );
}
