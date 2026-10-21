'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { ChevronsUpDown, UserCircle } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { RecordTable } from '@/components/shared/setting/record-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DIALOGS, PREVIEW_ROOT, S_MAP, SECTIONS, type SettingMapping } from '@/lib/settings-preview';

type Row = SettingMapping & { id: string };
const ROWS: Row[] = S_MAP.map((m) => ({ ...m, id: m.s }));
const COLUMNS: ColumnDef<Row>[] = [
  { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Setting" />, cell: ({ row }) => <span className="font-medium">{row.original.name}</span>, enableHiding: false },
  { accessorKey: 'home', header: 'New home', cell: ({ row }) => <Link href={row.original.href} className="text-primary underline-offset-4 hover:underline">{row.original.home}</Link> },
  { accessorKey: 'move', header: 'Change', cell: ({ row }) => <Badge variant={row.original.move === 'stays on the object' ? 'outline' : 'secondary'} className="font-normal">{row.original.move}</Badge> },
  { accessorKey: 'role', header: 'Who may change it' },
];

/** Where settings live now, how a person gets in, and where every one of the 43 settings in the review goes. */
export default function SettingsHome() {
  return (
    <PreviewPageLayout title="Settings" description="The proposed tree, with every page built from the same cards" history={false}>
      <section className="flex flex-col gap-3" id="entry">
        <h2 className="text-sm font-semibold">How a person gets in</h2>
        <div className="flex flex-wrap items-center gap-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" data-testid="avatar-menu">
                <UserCircle className="size-4" /> James Richardson <ChevronsUpDown className="size-3.5 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel>j.richardson@harborpine.example</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link href={`${PREVIEW_ROOT}/account`}>My account</Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href={`${PREVIEW_ROOT}/account#my-notifications`}>My notifications</Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem>Sign out</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" data-testid="team-menu">
                Operations <ChevronsUpDown className="size-3.5 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel>Operations</DropdownMenuLabel>
              <DropdownMenuItem asChild>
                <Link href={`${PREVIEW_ROOT}/team`}>Team settings</Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href={`${PREVIEW_ROOT}/workspace`}>Workspace settings</Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem>Switch team</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <p className="text-sm text-muted-foreground">The avatar menu opens My account; the team switcher opens Team and Workspace; Govern in the app sidebar opens Access, Policies, Security and Models.</p>
        </div>
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">The pages</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Page</TableHead>
              <TableHead>Under</TableHead>
              <TableHead>What it holds</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {SECTIONS.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">
                  <Link href={s.href} className="text-primary underline-offset-4 hover:underline">
                    {s.label}
                  </Link>
                </TableCell>
                <TableCell>{s.group}</TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{s.description}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
      <section className="flex flex-col gap-3" id="map">
        <h2 className="text-sm font-semibold">Where each of the 43 settings goes</h2>
        <RecordTable columns={COLUMNS} data={ROWS} nameOf={(r) => r.name} searchPlaceholder="Search settings, pages or roles…" />
      </section>
      <section className="flex flex-col gap-3" id="dialogs">
        <h2 className="text-sm font-semibold">Dialogs and their pages</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Dialog</TableHead>
              <TableHead>Same form on</TableHead>
              <TableHead>Opened from</TableHead>
              <TableHead>Server call</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {DIALOGS.map((d) => (
              <TableRow key={d.dialog}>
                <TableCell className="font-medium">{d.dialog}</TableCell>
                <TableCell>
                  <Link href={d.mother} className="text-primary underline-offset-4 hover:underline">
                    {d.motherLabel}
                  </Link>
                </TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{d.opensFrom}</TableCell>
                <TableCell>
                  <code className="font-mono text-xs">{d.calls}</code>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </PreviewPageLayout>
  );
}
