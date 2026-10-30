import type { Metadata } from 'next';

import { HostedFormPage } from '~/hosted-form-page';

// The link's token is in the address, so the page sends no Referer anywhere (next.config.ts also sets the header).
export const metadata: Metadata = { title: 'Form', referrer: 'no-referrer', robots: { index: false, follow: false } };

/**
 * A hosted form opened from its signed link (c-535): no sign-in, and only the form's title, description and fields.
 * agents-service checks the token on every read, upload and send; next.config.ts forbids framing this page.
 */
export default async function FormPage({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<{ t?: string | string[] }> }) {
  const { slug } = await params;
  const { t } = await searchParams;
  return <HostedFormPage slug={slug} token={typeof t === 'string' ? t : ''} />;
}
