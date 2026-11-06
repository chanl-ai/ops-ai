import type * as React from 'react';
import { Plus } from 'lucide-react';

import { HarborPineMark } from '@/components/auth/auth-form-wrapper';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { initials } from '@/lib/format';


/** The console's mark beside the app's, so the person sees which app the window signs them in to. */
function Brand({ app, logo }: { app: string; logo?: string | null }) {
  return (
    <div className="flex items-center gap-2" data-testid="sign-in-brand">
      <HarborPineMark />
      <Plus className="size-3.5 text-muted-foreground" aria-hidden />
      <Avatar className="size-8 rounded-md">
        {logo && <AvatarImage src={logo} alt="" />}
        <AvatarFallback className="rounded-md text-xs font-semibold">{initials(app)}</AvatarFallback>
      </Avatar>
      <span className="text-sm font-medium">{app}</span>
    </div>
  );
}

/** The sign-in window's one card, alone in the window: what is happening, then what the person can do next. */
export function SignInCard({
  title,
  description,
  children,
  footer,
  testId,
  app,
  logo,
}: {
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  testId: string;
  app?: string | null;
  logo?: string | null;
}) {
  return (
    <div className="flex min-h-svh items-center justify-center p-4">
      <div className="flex w-full max-w-sm flex-col">
        <Card className="shadow-none" data-testid={testId}>
          <CardHeader className="gap-3">
            {app && <Brand app={app} logo={logo} />}
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </CardHeader>
          {children && <CardContent className="flex flex-col gap-3">{children}</CardContent>}
          {footer && <CardFooter className="flex flex-wrap justify-end gap-2">{footer}</CardFooter>}
        </Card>
      </div>
    </div>
  );
}
