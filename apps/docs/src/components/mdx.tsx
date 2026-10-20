import { Callout } from 'fumadocs-ui/components/callout';
import { Step, Steps } from 'fumadocs-ui/components/steps';
import defaultMdxComponents from 'fumadocs-ui/mdx';
import type { MDXComponents } from 'mdx/types';

import { BoxDiagram } from './box-diagram';
import { DocStatus } from './doc-status';
import { FileLink } from './file-link';
import { OpsFigure } from './figure';
import { OpsMermaid } from './mermaid';
import { StatusBadge } from './status-badge';
import { SummaryCard, SummaryCards } from './summary-cards';

// The components src/lib/remark-ops-ai.mjs maps the markdown onto.
export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    BoxDiagram,
    Callout,
    DocStatus,
    FileLink,
    OpsFigure,
    OpsMermaid,
    Step,
    Steps,
    StatusBadge,
    SummaryCard,
    SummaryCards,
    ...components,
  };
}
