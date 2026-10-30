'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { HostedFormInput, HostedFormLink, HostedFormPatch } from '@/lib/types/forms';
import { useTeamQuery } from './team-query';

const key = (workflowId: string) => ['forms', workflowId] as const;

/** A workflow's hosted forms (c-535), without their tokens. */
export const useWorkflowForms = (workflowId: string, enabled = true) => useTeamQuery({ queryKey: key(workflowId), queryFn: () => api.forms.list(workflowId), enabled });

export function useCreateForm(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (input: HostedFormInput) => api.forms.create(workflowId, input), onSuccess: () => qc.invalidateQueries({ queryKey: key(workflowId) }) });
}

export function useRotateForm() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (form: HostedFormLink) => api.forms.rotate(form.id), onSuccess: (f) => qc.invalidateQueries({ queryKey: key(f.workflowId) }) });
}

export function useUpdateForm() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, patch }: { id: string; patch: HostedFormPatch }) => api.forms.update(id, patch), onSuccess: (f) => qc.invalidateQueries({ queryKey: key(f.workflowId) }) });
}

/** The full address of a link form's page. */
export const useFormPageUrl = () => (form: HostedFormLink) => api.forms.pageUrl(form);

/** A members-only form for the signed-in person; a refusal (another team's form) is shown at once, not retried. */
export const useMemberForm = (slug: string) => useTeamQuery({ queryKey: ['forms', 'members', slug], queryFn: () => api.forms.memberForm(slug), retry: false });

export const useSubmitMemberForm = (slug: string) => useMutation({ mutationFn: (values: Record<string, unknown>) => api.forms.submitMember(slug, values) });
