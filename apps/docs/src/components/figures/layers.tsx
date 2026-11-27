import { ArrowDown } from 'lucide-react';

import { FigureFrame } from './parts';

type Band = { title: string; text?: string; parts: { title: string; text?: string }[] };

/**
 * A system at a glance as stacked bands, read top to bottom: where work comes from, the platform's own layers inside
 * one frame, and the outside systems everything leaves to. The first and last bands sit outside the frame; the band
 * just above the last is the boundary every call leaves through and carries the accent. Written in markdown as
 * `<!-- site: layers -->` above a list.
 */
export function LayerMap({ data, caption, frame }: { data: string; caption?: string; frame?: string }) {
  const bands = JSON.parse(data) as Band[];
  const first = bands[0];
  const last = bands.length > 2 ? bands[bands.length - 1] : undefined;
  const inside = bands.slice(1, last ? -1 : undefined);
  const band = (b: Band, kind: 'outside' | 'inside' | 'exit') => (
    <div className={`ops-band ops-band-${kind}`}>
      <div className="ops-band-head">
        <p className="ops-band-title">{b.title}</p>
        {b.text && <p className="ops-band-text">{b.text}</p>}
      </div>
      <ul className="ops-band-parts">
        {b.parts.map((p) => (
          <li key={p.title}>
            <span className="ops-band-part-title">{p.title}</span>
            {p.text && <span className="ops-band-part-text">{p.text}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
  const arrow = <ArrowDown aria-hidden className="ops-band-arrow" strokeWidth={1.5} />;
  return (
    <FigureFrame caption={caption} stageClass="ops-layers">
        {band(first, 'outside')}
        {arrow}
        <div className="ops-layers-frame">
          {frame && <p className="ops-layers-frame-label">{frame}</p>}
          {inside.map((b, i) => (
            <div key={b.title} className="ops-layers-row">
              {i > 0 && arrow}
              {band(b, last && i === inside.length - 1 ? 'exit' : 'inside')}
            </div>
          ))}
        </div>
        {last && (
          <>
            {arrow}
            {band(last, 'outside')}
          </>
        )}
    </FigureFrame>
  );
}
