'use client';

import { toast } from 'sonner';

import { StepUpCancelled, useStepUpGate } from '@/components/auth/reauth-dialog';
import { type useChatThread, useDecideFromChat, useMessageFeedback, useWidgetAction } from '@/hooks/chat-queries';
import type { MessageFeedback, WidgetAction } from '@/lib/types/chat';

/**
 * What a person does to a thread's replies besides sending: copy, rate, and act on a widget, an approval included with
 * the same step-up as in Reviews. Shared by the chat page and an agent's test panel so both behave the same.
 * `stepUpDialog` must be rendered once by the caller.
 */
export function useThreadActions(threadId: string | undefined, thread: ReturnType<typeof useChatThread>) {
  const feedback = useMessageFeedback();
  const widgetAction = useWidgetAction();
  const decide = useDecideFromChat();
  // Approving from a chat widget needs the same step-up as in Reviews when the API marks it; the API enforces it.
  const stepUp = useStepUpGate();

  const copy = (text: string, what = 'Answer copied') =>
    navigator.clipboard.writeText(text).then(
      () => toast.success(what),
      () => toast.error('Couldn’t copy', { description: 'The browser blocked clipboard access.' }),
    );

  const onFeedback = (messageId: string, fb: MessageFeedback | null) => {
    if (!threadId) return;
    feedback.mutate(
      { threadId, messageId, feedback: fb },
      { onSuccess: () => fb?.rating === 'down' && toast.success('Thanks. The agent’s owner will see this.'), onError: (e) => toast.error('Couldn’t save feedback', { description: e.message }) },
    );
  };

  const onWidgetAction = async (messageId: string, widgetId: string, action: WidgetAction) => {
    if (!threadId) return;
    try {
      const target = thread.data?.messages.find((m) => m.id === messageId)?.widgets?.find((x) => x.id === widgetId);
      const money = action.type === 'approve' && target?.kind === 'approval' && !!target.stepUp;
      if (target?.kind === 'approval' && action.type !== 'submit') {
        // The decision goes to Reviews' route; the card's new state comes back with the thread.
        await stepUp.withStepUp(
          'Approving this action',
          (stepUpToken) =>
            decide.mutateAsync({ threadId, decision: action.type === 'approve' ? 'approved' : 'rejected', reason: action.type === 'reject' ? action.reason : undefined, stepUpToken: action.type === 'approve' ? stepUpToken : undefined }),
          { upfront: money },
        );
        const fresh = (await thread.refetch()).data?.messages.find((m) => m.id === messageId)?.widgets?.find((x) => x.id === widgetId);
        const second = fresh?.kind === 'approval' && fresh.state === 'awaiting_second';
        toast.success(action.type === 'reject' ? `Rejected ${target.reviewId}` : second ? `Your approval is recorded on ${target.reviewId}` : `Approved ${target.reviewId}`, {
          description: second ? 'A second reviewer must also approve it.' : 'The decision is on the review and in the audit trail.',
        });
        return;
      }
      const w = await widgetAction.mutateAsync({ threadId, messageId, widgetId, action });
      if (w.kind === 'form' && w.result) toast.success(w.result);
    } catch (e) {
      if (e instanceof StepUpCancelled) return;
      toast.error(action.type === 'submit' ? 'Couldn’t submit' : `Couldn’t ${action.type}`, { description: (e as Error).message });
    }
  };

  return { copy, onFeedback, onWidgetAction, stepUpDialog: stepUp.dialog };
}
