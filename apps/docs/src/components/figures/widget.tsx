import { pinsFor } from './notes';
import { PinNotes } from './parts';
import { type Fragment, UiFragment } from './ui-fragment';

/**
 * One product panel at its natural size, set beside the paragraph that follows it on a wide page and above it on a
 * phone. Same markdown as the annotated screen (`<!-- site: widget caption="..." -->` above a list), for a panel small
 * enough to sit inline: two to four rows, at most three notes.
 */
export function WidgetFigure({ data, caption }: { data: string; caption?: string }) {
  const fragment = JSON.parse(data) as Fragment;
  const { pins, notes } = pinsFor(fragment);
  return (
    <figure className="ops-fig ops-widget not-prose">
      <div className="ops-fig-stage">
        <UiFragment fragment={fragment} pins={pins} />
        <PinNotes notes={notes} compact />
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
