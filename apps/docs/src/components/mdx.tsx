import { Callout } from 'fumadocs-ui/components/callout';
import { Step, Steps } from 'fumadocs-ui/components/steps';
import defaultMdxComponents from 'fumadocs-ui/mdx';
import type { MDXComponents } from 'mdx/types';

import { AnnotatedFigure } from './annotated-figure';
import { BoxDiagram } from './box-diagram';
import { DocStatus } from './doc-status';
import { FileLink } from './file-link';
import { JourneyFigure } from './journey-figure';
import { LayerMap } from './layer-map';
import { OpsFigure } from './figure';
import { OpsMermaid } from './mermaid';
import { StatusBadge } from './status-badge';
import { SummaryCard, SummaryCards } from './summary-cards';

// The components src/lib/remark-ops-ai.mjs maps the markdown onto.
export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    AnnotatedFigure,
    BoxDiagram,
    Callout,
    DocStatus,
    FileLink,
    JourneyFigure,
    LayerMap,
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
