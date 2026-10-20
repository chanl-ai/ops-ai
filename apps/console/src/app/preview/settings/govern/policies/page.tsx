'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Plus } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Note } from '@/components/shared/setting/note';
import { Combobox } from '@/components/shared/setting/pickers';
import { RecordTable } from '@/components/shared/setting/record-table';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';
import { useViewerRole } from '@/lib/settings-preview-store';

import { GATES, POLICIES, type SampleGate } from '../../_sample/data';
import { mockSave } from '../../_sample/save';

const nameOf = (g: SampleGate) => g.name;
const COLUMNS: ColumnDef<SampleGate>[] = [
  { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Gate" />, cell: ({ row }) => <span className="font-medium">{row.original.name}</span>, enableHiding: false },
  { accessorKey: 'workflow', header: 'Workflow' },
  { accessorKey: 'reviewers', header: 'Reviewers' },
  { accessorKey: 'sla', header: 'SLA' },
  { accessorKey: 'onTimeout', header: 'On timeout' },
];
const TEAMS = [{ value: 'security', label: 'Security', hint: '3 admins' }, { value: 'risk', label: 'Risk and compliance', hint: '2 admins' }, { value: 'platform', label: 'Platform', hint: '4 admins' }];

/**
 * Govern › Policies (S14, S23). Each policy is one card with its options as choice cards, in the shape
 * GET and PUT /v1/policies will serve (c-186): key, value, default, role, effect. Every default is open.
 */
export default function PoliciesPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const [values, setValues] = React.useState<Record<string, string>>(Object.fromEntries(POLICIES.map((p) => [p.key, p.value])));
  const [team, setTeam] = React.useState<string | null>('security');
  return (
    <PreviewPageLayout
      title="Policies"
      description="Who may decide what, and which publishes need a review"
      actions={
        <Button onClick={() => mockSave('Gate')} disabled={!admin}>
          <Plus className="size-4" /> New gate
        </Button>
      }
    >
      <Note title="Every default is open">A policy you have not set behaves as its default. Changing one applies to new requests; open reviews keep the rule they were opened under.</Note>
      <section className="flex flex-col gap-4" data-testid="policy-cards">
        {POLICIES.map((p) => (
          <div key={p.key} id={p.key === 'publish_review' ? 'publish-reviews' : p.key} className="scroll-mt-20">
            <SettingCard
              id={`policy-${p.key}`}
              title={p.title}
              description={p.effect}
              help={`Default: ${p.options.find((o) => o.value === p.default)?.title}. Changed by ${p.role}. Key: ${p.key}`}
              onSave={() => mockSave(p.title)}
              dirty={values[p.key] !== p.value}
              locked={!admin}
              requiredRole={p.role}
            >
              <ChoiceCards name={p.key} label={p.title} choices={p.options} value={values[p.key]} onChange={(v) => setValues({ ...values, [p.key]: v })} />
            </SettingCard>
          </div>
        ))}
        <SettingCard id="policy-security_team" title="Security team" description="The team whose admins decide security reviews and manage egress, secrets and storage." help="Default: the team named Security. Changed by Admin. Key: security_team" onSave={() => mockSave('Security team')} dirty={team !== 'security'} locked={!admin} requiredRole="Admin">
          <div className="w-full sm:w-1/2">
            <Combobox options={TEAMS} value={team} onChange={setTeam} noun="teams" />
          </div>
        </SettingCard>
      </section>
      <section id="gates" className="flex scroll-mt-20 flex-col gap-3">
        <h2 className="text-sm font-semibold">Gate policies</h2>
        <RecordTable columns={COLUMNS} data={GATES} nameOf={nameOf} searchPlaceholder="Search gates…" />
      </section>
    </PreviewPageLayout>
  );
}
