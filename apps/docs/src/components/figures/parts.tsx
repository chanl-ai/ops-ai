import type { CSSProperties, ReactNode } from 'react';

/**
 * The parts every figure shares: the frame (a stage with one quiet accent wash, the caption under a hairline), the
 * numbered pin, the numbered notes that match the pins, and the numbered node of a step path. The caption is the
 * figure's accessible name. Nothing here takes focus: a figure is a picture, so drawn buttons are text.
 */
export function FigureFrame({
  caption,
  stageClass,
  children,
}: {
  caption?: string;
  stageClass?: string;
  children: ReactNode;
}) {
  return (
    <figure className="ops-fig not-prose">
      <div className={`ops-fig-stage${stageClass ? ` ${stageClass}` : ''}`}>{children}</div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/** A numbered pin. Hidden from screen readers: the order of the notes list carries the numbers. */
export function Pin({ n }: { n: number }) {
  return (
    <span className="ops-pin" aria-hidden>
      {n}
    </span>
  );
}

/** The notes beside a screen, in pin order. */
export function PinNotes({ notes, compact = false }: { notes: { label: string; note: string }[]; compact?: boolean }) {
  if (!notes.length) return null;
  return (
    <ol className={`ops-notes${compact ? ' ops-notes-compact' : ''}`}>
      {notes.map((n, i) => (
        <li key={`${n.label}-${i}`}>
          <Pin n={i + 1} />
          <div>
            <p className="ops-notes-label">{n.label}</p>
            <p>{n.note}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A numbered node on a step path (journey, timeline). The step's list position already carries the number. */
export function PathNode({ n, label }: { n?: number; label?: string }) {
  return (
    <span className="ops-node" aria-hidden>
      {label ?? n}
    </span>
  );
}

export const indexStyle = (i: number) => ({ '--i': i }) as CSSProperties;
