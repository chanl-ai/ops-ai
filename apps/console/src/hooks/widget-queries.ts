'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { WidgetTemplate, WidgetTemplateInput } from '@/lib/types/widgets';

// The agent page's widget picker and the /widgets page read the same list, so every write refreshes both (c-082).
const KEY = ['widget-templates'] as const;

export const useWidgetTemplates = () => useQuery({ queryKey: KEY, queryFn: () => api.widgets.list(), staleTime: 60_000 });
export const useWidgetTemplate = (widgetId: string) => useQuery({ queryKey: [...KEY, 'one', widgetId], queryFn: () => api.widgets.get(widgetId) });
export const useWidgetTemplatesPage = (p: ListParams) => usePagedQuery({ queryKey: [...KEY, 'page', p], queryFn: () => api.widgets.page(p) });

function useWidgetMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateWidget = () => useWidgetMutation((i: WidgetTemplateInput) => api.widgets.create(i));
export const useUpdateWidget = () => useWidgetMutation((i: { widgetId: string; input: WidgetTemplateInput }) => api.widgets.update(i.widgetId, i.input));
export const useRequestWidgetPublish = () => useWidgetMutation((w: Pick<WidgetTemplate, 'widgetId' | 'version'> & { note?: string }) => api.widgets.requestPublish(w.widgetId, w.version, w.note ?? ''));
export const useRetireWidget = () => useWidgetMutation((w: { widgetId: string; reason: string }) => api.widgets.retire(w.widgetId, w.reason));
