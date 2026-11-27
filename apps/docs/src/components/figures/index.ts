/**
 * The docs figure library. Authors never import these: a `<!-- site: <kind> -->` marker above a plain list (or code
 * blocks) becomes one of them at build time (./markdown.mjs), and components/mdx.tsx maps the names below. Every kind
 * with its markdown and when to use it: docs/contributing/figures.md.
 */
export { AnnotatedFigure } from './annotated';
export { BeforeAfterFigure } from './before-after';
export { CompareFigure } from './compare';
export { DecisionFigure } from './decision';
export { ExchangeFigure } from './exchange';
export { JourneyFigure } from './journey';
export { LayerMap } from './layers';
export { PreviewFigure } from './preview';
export { SequenceFigure } from './sequence';
export { StateFigure } from './state';
export { TimelineFigure } from './timeline';
export { WidgetFigure } from './widget';
