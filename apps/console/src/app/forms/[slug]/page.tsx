'use client';

import { useParams } from 'next/navigation';
import { ClipboardList } from 'lucide-react';

import { HostedForm, HostedFormRefused } from '@/components/forms/hosted-form';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { useMemberForm, useSubmitMemberForm } from '@/hooks/form-queries';

/**
 * A members-only hosted form (c-535): opened behind sign-in, sent as the signed-in person, and refused with why for
 * anyone outside the team that shares it. File fields pick or upload through Files, as the Start run dialog's do.
 */
export default function MemberFormPage() {
  const { slug } = useParams<{ slug: string }>();
  return <MemberForm slug={slug} />;
}

function MemberForm({ slug }: { slug: string }) {
  const form = useMemberForm(slug);
  const submit = useSubmitMemberForm(slug);
  if (form.isPending) return <PageSkeleton statCards={0} tableRows={3} showToolbar={false} />;
  if (form.isError || !form.data) {
    return (
      <PageLayout icon={ClipboardList} title="Form">
        <div className="mx-auto w-full max-w-lg min-w-0">
          <HostedFormRefused title="This form cannot be opened" message={form.error?.message ?? 'Ask whoever sent it to you for a new link.'} />
        </div>
      </PageLayout>
    );
  }
  return (
    <PageLayout icon={ClipboardList} title={form.data.title} description={form.data.description || 'A form your team shares. Sending it starts a run as you.'}>
      <div className="mx-auto w-full max-w-lg min-w-0">
        <HostedForm form={form.data} showHeading={false} onSubmit={(values) => submit.mutateAsync(values)} />
      </div>
    </PageLayout>
  );
}
