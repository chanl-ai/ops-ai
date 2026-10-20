'use client';

import { useRouter } from 'next/navigation';

import { ConnectMailbox } from '../../_parts/connect-mailbox';
import { ChannelsPageLayout } from '../../_parts/layout';
import { ROOT } from '../../_sample/data';

/** The connect form's page shell; the trigger sheet opens the same form as a dialog. */
export default function ConnectMailboxPage() {
  const router = useRouter();
  return (
    <ChannelsPageLayout back={`${ROOT}/email`} title="Connect a mailbox" description="Pick the provider, point it at a folder, test it, and choose how replies go out">
      <ConnectMailbox shell="page" onConnected={(id) => router.push(`${ROOT}/email/${id}`)} />
    </ChannelsPageLayout>
  );
}
