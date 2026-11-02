'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { openSignIn } from '@/components/connections/sign-in';
import { LoadingButton } from '@/components/shared/loading-button';
import { useSession } from '@/hooks/auth-queries';
import { useCan } from '@/hooks/me-queries';
import { useStartSignIn } from '@/hooks/systems-queries';
import { sdk } from '@/lib/api/ops-sdk';
import type { Review } from '@/lib/types/domain';

/**
 * A run waiting for a person's own account of an app (kind connect_account, Apps (final) frame 11). The person it waits
 * for connects here, and the run goes on by itself once they have. Where the app has a team account, someone allowed
 * to run as it (connections.run, admins by default) can let the step go on as the team account instead.
 */
export function ConnectWait({ review }: { review: Review }) {
  const c = review.connect;
  const qc = useQueryClient();
  const { session } = useSession();
  const start = useStartSignIn();
  const mayRunAsTeam = useCan('connections', 'run') !== false;
  const asTeam = useMutation({
    mutationFn: () => sdk((ops) => ops.raw.agents.reviews_run_as_team_account({ path: { thread_id: review.id } })),
    onSuccess: () => {
      toast.success('The run goes on as the team account');
      void qc.invalidateQueries({ queryKey: ['reviews'] });
    },
    onError: (e: Error) => toast.error('Couldn’t run it as the team account', { description: e.message }),
  });
  if (!c) return null;
  // Only the person it waits for can connect their own account; anyone else sees whom it waits for.
  const mine = !!c.person && c.person === session?.user.email;
  const connect = () =>
    c.connectionId &&
    start.mutate(
      { connectionId: c.connectionId, environment: 'production', account: 'self' },
      { onSuccess: (s) => void openSignIn(s, c.connectionId!), onError: (e) => toast.error('Couldn’t start the sign-in', { description: e.message }) },
    );
  return (
    <div className="flex flex-col gap-3 p-4" data-testid="connect-wait">
      <p className="text-xs text-muted-foreground">
        {review.workflowName || 'A run'} uses {c.app} as {mine ? 'you' : (c.person ?? 'the person who started it')}. {mine ? 'Connect once; the run goes on by itself.' : 'It goes on by itself once they connect.'}
      </p>
      <div className="flex flex-wrap gap-2">
        {mine && c.connectionId && (
          <LoadingButton size="sm" isLoading={start.isPending} onClick={connect} data-testid="connect-wait-me">
            <ExternalLink /> Connect my account
          </LoadingButton>
        )}
        {c.teamAccount && mayRunAsTeam && (
          <LoadingButton size="sm" variant="outline" isLoading={asTeam.isPending} onClick={() => asTeam.mutate()} data-testid="connect-wait-team">
            Run as the team account
          </LoadingButton>
        )}
      </div>
    </div>
  );
}
