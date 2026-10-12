import { redirect } from 'next/navigation';

/** A source's own page moved under Connections; old links land on it. */
export default async function SourceRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/integrations/sources/${id}`);
}
