import { Reveal } from './reveal';
import { type Fragment, UiFragment } from './ui-fragment';

/**
 * A flow told as the screens a person would see at each step, joined by a numbered path, with what the step means
 * beside it. Written in markdown as `<!-- site: journey -->` above a numbered list (src/lib/remark-ops-ai.mjs).
 */
export function JourneyFigure({ data, caption }: { data: string; caption?: string }) {
  const steps = JSON.parse(data) as (Fragment & { callout: string })[];
  return (
    <figure className="ops-figure ops-fig not-prose">
      <Reveal className="ops-fig-stage">
        <ol className="ops-journey">
          {steps.map((step, i) => (
            <li key={step.title} className="ops-journey-step" style={{ '--i': i } as React.CSSProperties}>
              <span className="ops-journey-node" aria-hidden>
                {i + 1}
              </span>
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
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
