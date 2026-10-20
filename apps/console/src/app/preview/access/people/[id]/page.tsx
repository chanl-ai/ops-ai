'use client';

import * as React from 'react';
import { CheckCircle2, SearchCheck, User, XCircle } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

import { ACTIONS, AREAS, grantsOf, label, PERSON } from '../../_sample/access';

/** Mock (c-150): a person's page: what they can do in the team, each action with the role that grants it. */
export default function PersonMock() {
  const grants = grantsOf(PERSON.roles);
  const [checking, setChecking] = React.useState(false);
  const [area, setArea] = React.useState('reviews');
  const [action, setAction] = React.useState('decide');
  const granted = grants.find((g) => g.area === area && g.action === action);
  return (
    <PageLayout
      icon={User}
      title={PERSON.name}
      description={`${PERSON.email} · ${PERSON.team}`}
      backHref="/access"
      actions={
        <Button variant="outline" onClick={() => setChecking(true)} data-testid="check-access">
          <SearchCheck className="size-4" /> Check access
        </Button>
      }
    >
      <RecordLayout
        rail={
          <AttributeCard title="Access" icon={User}>
            <FieldRow label="Team" value={PERSON.team} />
            <FieldRow label="Roles" value={PERSON.roles.map((r) => label(r)).join(', ')} />
            <FieldRow label="Permissions" value={String(grants.length)} />
          </AttributeCard>
        }
      >
        <Section title="What they can do" description="In Operations, from the roles they hold. A missing action is not allowed.">
          <div className="flex flex-col divide-y">
            {AREAS.filter((a) => grants.some((g) => g.area === a)).map((a) => (
              <div key={a} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5" data-testid={`grants-${a}`}>
                <span className="w-40 shrink-0 text-sm font-medium">{label(a)}</span>
                <span className="flex flex-wrap gap-1.5">
                  {grants
                    .filter((g) => g.area === a)
                    .map((g) => (
                      <Badge key={g.action} variant="outline" title={`Granted by ${g.role}`} className="font-normal">
                        {label(g.action)}
                        {g.scope === 'own' ? ' · own' : ''}
                      </Badge>
                    ))}
                </span>
                <span className="ml-auto text-xs text-muted-foreground">from {[...new Set(grants.filter((g) => g.area === a).map((g) => g.role))].join(', ')}</span>
              </div>
            ))}
          </div>
        </Section>
      </RecordLayout>
      <DialogShell
        open={checking}
        onOpenChange={setChecking}
        size="md"
        title={`Check ${PERSON.name}'s access`}
        description="The same check the services run, with the workspace's policies; recorded in the audit log."
        footer={<Button onClick={() => setChecking(false)}>Done</Button>}
      >
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="check-area" label="Area">
              <Select value={area} onValueChange={setArea}>
                <SelectTrigger id="check-area" className="w-full bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AREAS.map((a) => (
                    <SelectItem key={a} value={a}>
                      {label(a)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="check-action" label="Action">
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger id="check-action" className="w-full bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACTIONS.map((a) => (
                    <SelectItem key={a} value={a}>
                      {label(a)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
          {granted ? (
            <Alert data-testid="check-result" data-allowed="true">
              <CheckCircle2 className="text-success-text" />
              <AlertTitle>Allowed{granted.scope === 'own' ? ' on their own records' : ''}</AlertTitle>
              <AlertDescription>Granted by {granted.role}, which {PERSON.name} holds in Operations.</AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive" data-testid="check-result" data-allowed="false">
              <XCircle />
              <AlertTitle>Not allowed</AlertTitle>
              <AlertDescription>
                None of {PERSON.name}&apos;s roles grants {label(action)} on {label(area)}. A Reviewer or Admin of Operations holds it; Priya Shah can grant it.
              </AlertDescription>
            </Alert>
          )}
        </div>
      </DialogShell>
    </PageLayout>
  );
}
