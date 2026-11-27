import { ArrowRight } from 'lucide-react';
import type { CSSProperties } from 'react';

import { FigureFrame } from './parts';

type Seq = { actors: string[]; steps: { from: number; to: number; text: string; note?: string }[] };

/**
 * Who talks to whom, in order. Wide: one lifeline per participant and each message an arrow between two of them.
 * Narrow: the same ordered list as rows, each naming its two ends, so nothing shrinks below reading size. Markdown:
 * `<!-- site: sequence caption="..." -->` above a numbered list of `**From → To**: message`; a nested bullet is a note
 * under that message. At most five participants.
 */
export function SequenceFigure({ data, caption }: { data: string; caption?: string }) {
  const { actors, steps } = JSON.parse(data) as Seq;
  const lanes = { '--n': actors.length } as CSSProperties;
  return (
    <FigureFrame caption={caption}>
      <div className="ops-seq" style={lanes}>
        <ul className="ops-seq-actors" aria-label="Participants">
          {actors.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        <div className="ops-seq-lifelines" aria-hidden>
          {actors.map((a) => (
            <span key={a} />
          ))}
        </div>
        <ol className="ops-seq-steps">
          {steps.map((s, i) => {
            const lo = Math.min(s.from, s.to);
            const span = Math.abs(s.to - s.from) + 1;
            const place = { gridColumn: `${lo + 1} / span ${span}`, gridRow: i + 1, '--k': span } as CSSProperties;
            const dir = s.to === s.from ? 'self' : s.to > s.from ? 'right' : 'left';
            return (
              <li key={i} className="ops-seq-step">
                <div className={`ops-seq-msg ops-seq-${dir}`} style={place}>
                  <p className="ops-seq-ends">
                    <span className="ops-seq-num">{i + 1}</span>
                    <span>{actors[s.from]}</span>
                    <ArrowRight aria-label="to" className="ops-seq-to" strokeWidth={1.5} />
                    <span>{actors[s.to]}</span>
                  </p>
                  <p className="ops-seq-text">
                    <span className="ops-seq-num ops-seq-num-wide" aria-hidden>
                      {i + 1}
                    </span>
                    {s.text}
                  </p>
                  <span className="ops-seq-line" aria-hidden />
                  {s.note && <p className="ops-seq-note">{s.note}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </FigureFrame>
  );
}
