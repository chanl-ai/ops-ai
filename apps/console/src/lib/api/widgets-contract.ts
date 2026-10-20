import type { ListParams, ListResult, OptionsPage, OptionsParams } from '@/lib/types/query';
import type { WidgetTemplate, WidgetTemplateInput } from '@/lib/types/widgets';

/**
 * Widget templates an agent pins and fills in chat (c-082, `.codeloop/wiki/concepts/chat-widgets.md`), served by
 * agents-service `/v1/widgets`: the seeded platform library plus the caller's team's widgets. A widget from the seeded
 * library cannot be edited (409).
 */
export interface WidgetsApi {
  /** Every template's latest version: published ones from the library, plus drafts and reviews on a backend that authors. */
  list(): Promise<WidgetTemplate[]>;
  /** One template's latest version; 404 when the id names none. */
  get(widgetId: string): Promise<WidgetTemplate>;
  /** One page of those whose name matches the search: the seeded library's first, then the team's, by name. */
  page(p: ListParams): Promise<ListResult<WidgetTemplate>>;
  /** The widget picker: published widgets searched on the server; one needing a tool outside `granted` is disabled with the reason (c-136). */
  options(p: OptionsParams, granted: string[]): Promise<OptionsPage>;
  /** A new template, saved as draft version 1. */
  create(input: WidgetTemplateInput): Promise<WidgetTemplate>;
  /** Saves the next version as a draft; 422 when the tree, bindings or schema fail the catalogue check. */
  update(widgetId: string, input: WidgetTemplateInput): Promise<WidgetTemplate>;
  /** Opens a review decided in Reviews by someone other than whoever saved it; in dev it is approved at once. */
  requestPublish(widgetId: string, version: number, note: string): Promise<WidgetTemplate>;
  /** Terminal: new pins are refused; agents that pin it keep their version. */
  retire(widgetId: string, reason: string): Promise<WidgetTemplate>;
}
