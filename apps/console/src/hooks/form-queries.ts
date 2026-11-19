'use client';

/** Hosted forms on the generated SDK: a workflow's shared forms (paged), making, rotating and pausing one, and a members-only form. */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { embedPageOrigin, publicFormPage } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { HostedFormInput, HostedFormLink, HostedFormPatch } from '@/lib/types/forms';
import { useTeamInfiniteQuery, useTeamQuery } from './team-query';

/** True when the embed app's origin is set, so a signed link has a page that can open it. */
export const usePublicFormPage = () => publicFormPage;

const key = (workflowId: string) => ['forms', workflowId] as const;
const PAGE = 20;

/** A workflow's hosted forms, without their tokens, a page at a time (`GET /v1/workflows/{id}/forms`); the next page is asked for on request. */
export const useWorkflowForms = (workflowId: string, enabled = true) =>
  useTeamInfiniteQuery({
    queryKey: key(workflowId),
    queryFn: ({ pageParam }) => sdk((ops) => ops.raw.agents.forms_workflow_forms({ path: { workflow_id: workflowId }, query: { page: pageParam, pageSize: PAGE } })),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.pagination.hasNext ? last.pagination.page + 1 : undefined),
    enabled,
  });

export function useCreateForm(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: HostedFormInput) => sdk((ops) => ops.raw.agents.forms_create_form({ path: { workflow_id: workflowId }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(workflowId) }),
  });
}

export function useRotateForm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (form: HostedFormLink) => sdk((ops) => ops.raw.agents.forms_rotate_form({ path: { form_id: form.id } })),
    onSuccess: (f) => qc.invalidateQueries({ queryKey: key(f.workflowId) }),
  });
}

export function useUpdateForm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: HostedFormPatch }) => sdk((ops) => ops.raw.agents.forms_update_form({ path: { form_id: id }, body: patch })),
    onSuccess: (f) => qc.invalidateQueries({ queryKey: key(f.workflowId) }),
  });
}

/** The full address of a link form's page: the embed app's host (NEXT_PUBLIC_OPS_EMBED_URL) and the form's path. */
export const useFormPageUrl = () => (form: HostedFormLink) => (embedPageOrigin ? `${embedPageOrigin}${form.url}` : form.url);

/** A members-only form for the signed-in person; a refusal (another team's form) is shown at once, not retried. */
export const useMemberForm = (slug: string) =>
  useTeamQuery({ queryKey: ['forms', 'members', slug], queryFn: () => sdk((ops) => ops.raw.agents.forms_member_form({ path: { slug } })), retry: false });

/** Starts a run as the signed-in person. */
export const useSubmitMemberForm = (slug: string) =>
  useMutation({ mutationFn: (values: Record<string, unknown>) => sdk((ops) => ops.raw.agents.forms_submit_member({ path: { slug }, body: { values } })) });
