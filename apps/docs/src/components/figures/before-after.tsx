import { FigureFrame } from './parts';

type Side = { label: string; text?: string; points: string[] };

/**
 * Two labelled sides of one change, read left to right on a wide page and top to bottom on a phone: the first side is
 * muted (how it is without the feature, or before), the second carries the accent. Markdown:
 * `<!-- site: before-after caption="..." -->` above a two-item list, `- **Today**: ...` then `- **With Ops AI**: ...`;
 * nested bullets are the side's points, matched in order so the two sides read across.
 */
export function BeforeAfterFigure({ data, caption }: { data: string; caption?: string }) {
  const sides = JSON.parse(data) as Side[];
  return (
    <FigureFrame caption={caption}>
      <div className="ops-pair">
        {sides.map((s, i) => (
          <section key={s.label} className={`ops-pair-side ops-pair-${i === 0 ? 'before' : 'after'}`} aria-label={s.label}>
            <p className="ops-pair-label">{s.label}</p>
            {s.text && <p className="ops-pair-text">{s.text}</p>}
            {s.points.length > 0 && (
              <ul className="ops-pair-points">
                {s.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </FigureFrame>
  );
}
