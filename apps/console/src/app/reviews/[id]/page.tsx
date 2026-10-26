import { redirect } from 'next/navigation';

/**
 * A task's old address: Human Tasks opens every task on the queue and task page (c-460), in ?review= as every other
 * link into a task reads it, so this one redirects there.
 */
export default async function TaskRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/reviews?review=${encodeURIComponent(decodeURIComponent(id))}`);
}
