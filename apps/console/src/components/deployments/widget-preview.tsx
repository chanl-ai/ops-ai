'use client';

import * as React from 'react';
import { AlertCircle } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useWidgetPreviewSession, useWidgetScriptUrl } from '@/hooks/widget-deployment-queries';
import type { WidgetDeployment } from '@/lib/types/widget-deployments';

const ERRORS: Record<string, string> = {
  origin_not_allowed: 'The embed app refused the console as a page for this embed.',
  session_unavailable: 'Ops AI did not start a preview session for you.',
  unreachable: 'The embed app is not reachable. Start it with the local stack (make up), then open the preview again.',
};

/**
 * Preview as a person: the bank's page as the signed-in builder would see it, in a frame of its own. The frame loads
 * the real loader from the embed app and asks agents-service for a preview session for this person, bound to the
 * console's origin, so the chat, its sign-in and its sessions are the ones a customer's page gets. The loader runs once
 * per page, so it gets a document of its own instead of the console's.
 */
export function WidgetPreviewSheet({ deployment, tenant, me, open, onOpenChange }: { deployment: WidgetDeployment; tenant: string; me: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const script = useWidgetScriptUrl();
  const preview = useWidgetPreviewSession();
  const mint = preview.mutateAsync;
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (!open) return setError(undefined);
    // The frame's document shares the console's origin, so it can reach these two functions on its parent.
    const w = window as unknown as Record<string, unknown>;
    w.__opsPreviewSession = () => mint(deployment.id);
    w.__opsPreviewError = (code: string) => setError(ERRORS[code] ?? `The chat stopped: ${code}.`);
    return () => {
      delete w.__opsPreviewSession;
      delete w.__opsPreviewError;
    };
  }, [open, deployment.id, mint]);
  // The embed app reads the page origin from the Referer, so the frame says to send it.
  const doc = `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="origin"><style>body{font-family:system-ui,sans-serif;margin:24px;color:#444}</style></head><body>
<p>A page on ${deployment.origins[0] ?? 'your site'}, signed in as ${me.replace(/[<&"]/g, '')}.</p>
<script src="${script}" onerror="parent.__opsPreviewError('unreachable')"></script>
<script>
  if (window.OpsChat) {
    OpsChat.on('error', function (e) { parent.__opsPreviewError(e.code); });
    OpsChat.init({ deployment: ${JSON.stringify(deployment.id)}, tenant: ${JSON.stringify(tenant)}, getSession: function () { return parent.__opsPreviewSession(); } }).then(function () { OpsChat.open(); });
  }
</script></body></html>`;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-3 sm:max-w-xl" data-testid="widget-preview">
        <SheetHeader>
          <SheetTitle>Preview {deployment.name}</SheetTitle>
          <SheetDescription>The chat as {me} sees it on the bank&apos;s page. It is a real session: what you send reaches the agent and shows in Conversations.</SheetDescription>
        </SheetHeader>
        {error ? (
          <Alert variant="destructive" data-testid="widget-preview-error">
            <AlertCircle />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {open ? <iframe title={`Preview of ${deployment.name}`} srcDoc={doc} className="min-h-0 w-full flex-1 rounded-md border bg-background" data-testid="widget-preview-frame" /> : null}
      </SheetContent>
    </Sheet>
  );
}
