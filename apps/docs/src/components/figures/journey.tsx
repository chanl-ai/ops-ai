import { FigureFrame, PathNode, indexStyle } from './parts';
import { Reveal } from './reveal';
import { type Fragment, UiFragment } from './ui-fragment';

/**
 * A flow told as the screens a person would see at each step, joined by a numbered path, with what the step means
 * beside it. Written in markdown as `<!-- site: journey -->` above a numbered list (./markdown.mjs).
 */
export function JourneyFigure({ data, caption }: { data: string; caption?: string }) {
  const steps = JSON.parse(data) as (Fragment & { callout: string })[];
  return (
    <FigureFrame caption={caption}>
      <Reveal>
        <ol className="ops-journey">
          {steps.map((step, i) => (
            <li key={step.title} className="ops-journey-step" style={indexStyle(i)}>
              <PathNode n={i + 1} />
              <div className="ops-journey-ui">
                <UiFragment fragment={step} showTitle={false} />
              </div>
              <div className="ops-journey-callout">
                <p className="ops-journey-callout-title">{step.title}</p>
                <p>{step.callout}</p>
              </div>
            </li>
          ))}
        </ol>
      </Reveal>
    </FigureFrame>
  );
}
