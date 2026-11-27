import { ArrowDown, SquareTerminal } from 'lucide-react';

import { FigureFrame } from './parts';

type Half = { lang: string; title: string; code: string; status?: string };

const tone = (status?: string) => (!status ? 'step' : /^2/.test(status) ? 'done' : /^[45]/.test(status) ? 'stop' : 'step');

/**
 * A command or API request and what comes back, drawn as two product panels. Markdown:
 * `<!-- site: exchange caption="..." -->` above two code blocks: the request (```` ```bash title="Start a run" ````)
 * and the response (```` ```json status="201 Created" ````). Keep each to about twelve lines; cut fields a reader
 * does not need for the point being made.
 */
export function ExchangeFigure({ data, caption }: { data: string; caption?: string }) {
  const { request, response } = JSON.parse(data) as { request: Half; response: Half };
  const panel = (h: Half, kind: 'request' | 'response') => (
    <div className={`ops-ui ops-exchange-${kind}`}>
      <div className="ops-ui-bar">
        {kind === 'request' && <SquareTerminal aria-hidden className="ops-ui-icon" strokeWidth={1.5} />}
        <span>{h.title}</span>
        {h.status && <span className={`ops-chip ops-chip-${tone(h.status)} ops-exchange-status`}>{h.status}</span>}
      </div>
      <pre className="ops-exchange-code">
        <code>{h.code}</code>
      </pre>
    </div>
  );
  return (
    <FigureFrame caption={caption}>
      <div className="ops-exchange">
        {panel(request, 'request')}
        <ArrowDown aria-hidden className="ops-exchange-arrow" strokeWidth={1.5} />
        {panel(response, 'response')}
      </div>
    </FigureFrame>
  );
}
