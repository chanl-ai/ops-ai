import { pinsFor } from './notes';
import { FigureFrame, PinNotes } from './parts';
import { type Fragment, UiFragment } from './ui-fragment';

/**
 * One screen drawn large, with a numbered note pinned to each part that protects the reader, listed beside it in the
 * same order. Markdown: `<!-- site: annotated caption="..." -->` above a list; a field's nested bullet is its note.
 */
export function AnnotatedFigure({ data, caption }: { data: string; caption?: string }) {
  const fragment = JSON.parse(data) as Fragment;
  const { pins, notes } = pinsFor(fragment);
  return (
    <FigureFrame caption={caption}>
      <div className="ops-annotated">
        <div className="ops-annotated-screen">
          <UiFragment fragment={fragment} pins={pins} size="lg" />
        </div>
        <PinNotes notes={notes} />
      </div>
    </FigureFrame>
  );
}
