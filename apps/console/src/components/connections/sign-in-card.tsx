import type * as React from 'react';
import { Plug } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';

/** The sign-in window's one card: what is happening, then what the person can do next. */
export function SignInCard({ title, description, children, footer, testId }: { title: string; description?: React.ReactNode; children?: React.ReactNode; footer?: React.ReactNode; testId: string }) {
  return (
    <PageLayout icon={Plug} title="Connect your account">
      <div className="mx-auto flex w-full max-w-md flex-col">
        <Card className="shadow-none" data-testid={testId}>
          <CardHeader>
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </CardHeader>
          {children && <CardContent className="flex flex-col gap-3">{children}</CardContent>}
          {footer && <CardFooter className="flex flex-wrap justify-end gap-2">{footer}</CardFooter>}
        </Card>
      </div>
    </PageLayout>
  );
}
