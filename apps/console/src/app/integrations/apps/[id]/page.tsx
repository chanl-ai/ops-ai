'use client';

import { useParams } from 'next/navigation';

import { AppPageView } from '@/components/connections/app-page';

/** An app's page: its accounts, tools, skills, sign-ins, runs and settings, from GET /v1/apps/{id}. */
export default function AppPage() {
  const { id } = useParams<{ id: string }>();
  return <AppPageView appId={decodeURIComponent(id)} />;
}
