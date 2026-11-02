import { CircleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

/**
 * A tool saved before sign-in headers were refused still sends one (its operation's `signInHeader`); the app's Account
 * should sign instead. Shown on every tool page layout: the REST tool page and the function workbench.
 */
export function SignInHeaderNotice({ header }: { header?: string | null }) {
  if (!header) return null;
  return (
    <Alert variant="destructive" data-testid="sign-in-header">
      <CircleAlert className="size-4" />
      <AlertTitle>This tool sends a sign-in header; move it to the app</AlertTitle>
      <AlertDescription>
        Its {header} header carries a key. Remove it here and set the key on the app’s Account, which signs every call; the tool can’t be saved again until then.
      </AlertDescription>
    </Alert>
  );
}
