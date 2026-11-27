import { FigureFrame } from './parts';

type Ask = { question: string; text?: string; branches: { answer: string; outcome?: string; next?: Ask }[] };

function Question({ ask }: { ask: Ask }) {
  return (
    <div className="ops-ask">
      <div className="ops-ask-q">
        <p className="ops-ask-title">{ask.question}</p>
        {ask.text && <p className="ops-ask-text">{ask.text}</p>}
      </div>
      <ul className="ops-ask-branches">
        {ask.branches.map((b) => (
          <li key={b.answer} className="ops-ask-branch">
            <span className="ops-chip ops-chip-step">{b.answer}</span>
            {b.outcome && <p className={`ops-ask-outcome${b.next ? ' ops-ask-outcome-lead' : ''}`}>{b.outcome}</p>}
            {b.next && <Question ask={b.next} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A short if-this-then-that tree: a question, two or three answers, each ending in an outcome or one further question,
 * at most three questions deep. Markdown: `<!-- site: decision caption="..." -->` above a one-item list whose item is
 * the question in bold and whose nested bullets are `**Answer**: outcome`, optionally with a nested question.
 */
export function DecisionFigure({ data, caption }: { data: string; caption?: string }) {
  return (
    <FigureFrame caption={caption}>
      <Question ask={JSON.parse(data) as Ask} />
    </FigureFrame>
  );
}
