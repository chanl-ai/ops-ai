import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * The card every sign-in screen sits in: the form on the left, the Northfield panel on the right on wide screens.
 * Adapted from chanl-admin's auth wrapper with this app's tokens and copy.
 */
export function AuthFormWrapper({ children, className, showPanel = true }: { children: React.ReactNode; className?: string; showPanel?: boolean }) {
  return (
    <div className={cn('flex flex-col gap-6', className)}>
      <Card className="overflow-hidden p-0">
        <CardContent className={cn('grid p-0', showPanel && 'md:grid-cols-2')}>
          <div className="p-6 md:p-8">{children}</div>
          {showPanel && (
            <div className="relative hidden bg-gradient-to-br from-primary/90 to-primary/70 md:block dark:from-primary/80 dark:to-primary/50">
              <div className="relative flex h-full flex-col justify-between p-8 text-primary-foreground">
                <div className="flex items-center gap-2">
                  <NorthfieldMark className="bg-white/20 text-white" />
                  <span className="text-lg font-semibold">Northfield Bank</span>
                </div>
                <div className="flex flex-col gap-2">
                  <h2 className="text-2xl font-semibold">Ops AI</h2>
                  <p className="text-sm text-primary-foreground/80">Agents, workflows and the people who review them, in one console.</p>
                </div>
                <p className="text-xs text-primary-foreground/60">Signed-in activity is recorded in the audit log.</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      <p className="text-center text-xs text-balance text-muted-foreground">For Northfield staff. Need access? Ask your workspace admin.</p>
    </div>
  );
}

export function NorthfieldMark({ className }: { className?: string }) {
  return <span className={cn('flex size-8 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground', className)}>N</span>;
}

/** Heading block shared by the forms. */
export function AuthHeading({ title, description, icon }: { title: string; description?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      {icon && <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">{icon}</div>}
      <h1 className="text-2xl font-semibold">{title}</h1>
      {description && <p className="text-balance text-muted-foreground">{description}</p>}
    </div>
  );
}

export function AuthError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-md border border-destructive/20 bg-destructive/10 p-3 text-center text-sm text-destructive" role="alert" data-testid="auth-error">
      {message}
    </p>
  );
}
