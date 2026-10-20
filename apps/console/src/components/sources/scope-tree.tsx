'use client';

import * as React from 'react';
import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen } from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import type { SourceType } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

export interface TreeNode {
  id: string
  label: string
  kind: 'site' | 'folder' | 'space' | 'repo' | 'page' | 'category' | 'drive' | 'type'
  count?: number
  children?: TreeNode[]
}

/** What each connected app exposes to pick from; a real backend lists these from the connection. */
export const TREES: Partial<Record<SourceType, TreeNode[]>> = {
  sharepoint: [
    { id: 'site-people', label: 'People Operations', kind: 'site', children: [{ id: 'lib-docs', label: 'Documents', kind: 'folder', children: [{ id: 'f-policies', label: 'Policies', kind: 'folder', count: 612 }, { id: 'f-forms', label: 'Forms', kind: 'folder', count: 200 }, { id: 'f-archive', label: 'Archive', kind: 'folder', count: 1_204 }] }, { id: 'lib-templates', label: 'Templates', kind: 'folder', count: 44 }] },
    { id: 'site-finance', label: 'Finance', kind: 'site', children: [{ id: 'f-close', label: 'Month-end close', kind: 'folder', count: 380 }, { id: 'f-audit', label: 'Audit', kind: 'folder', count: 120 }] },
    { id: 'site-branch', label: 'Branch Network', kind: 'site', children: [{ id: 'f-ops', label: 'Operations manuals', kind: 'folder', count: 96 }] },
  ],
  confluence: [
    { id: 'ENG', label: 'ENG · Engineering', kind: 'space', count: 212 },
    { id: 'PLAT', label: 'PLAT · Platform', kind: 'space', count: 98 },
    { id: 'SRE', label: 'SRE · Reliability', kind: 'space', count: 70 },
    { id: 'PROD', label: 'PROD · Product', kind: 'space', count: 340 },
    { id: 'HR', label: 'HR · People', kind: 'space', count: 41 },
  ],
  gdrive: [
    { id: 'sd-legal', label: 'Legal (shared drive)', kind: 'drive', children: [{ id: 'g-contracts', label: 'Contracts', kind: 'folder', count: 58 }, { id: 'g-templates', label: 'Templates', kind: 'folder', count: 12 }] },
    { id: 'sd-marketing', label: 'Marketing (shared drive)', kind: 'drive', children: [{ id: 'g-brand', label: 'Brand', kind: 'folder', count: 140 }, { id: 'g-campaigns', label: 'Campaigns 2026', kind: 'folder', count: 322 }] },
  ],
  github: [
    { id: 'platform-docs', label: 'northfield-bank/platform-docs', kind: 'repo', count: 214 },
    { id: 'api-gateway', label: 'northfield-bank/api-gateway', kind: 'repo', count: 31 },
    { id: 'mobile-app', label: 'northfield-bank/mobile-app', kind: 'repo', count: 12 },
    { id: 'infra', label: 'northfield-bank/infra', kind: 'repo', count: 64 },
  ],
  notion: [
    { id: 'n-wiki', label: 'Product wiki', kind: 'page', count: 88, children: [{ id: 'n-specs', label: 'Specs', kind: 'page', count: 40 }, { id: 'n-research', label: 'Research repository', kind: 'page', count: 22 }] },
    { id: 'n-roadmap', label: 'Roadmap', kind: 'page', count: 14 },
    { id: 'n-meetings', label: 'Meeting notes', kind: 'page', count: 410 },
  ],
  zendesk: [
    { id: 'z-accounts', label: 'Accounts', kind: 'category', count: 62 },
    { id: 'z-cards', label: 'Cards', kind: 'category', count: 48 },
    { id: 'z-loans', label: 'Loans and mortgages', kind: 'category', count: 37 },
    { id: 'z-internal', label: 'Internal (agents only)', kind: 'category', count: 120 },
  ],
  salesforce: [
    { id: 'sf-faq', label: 'FAQ', kind: 'type', count: 210 },
    { id: 'sf-howto', label: 'How-to', kind: 'type', count: 96 },
    { id: 'sf-policy', label: 'Policy', kind: 'type', count: 44 },
  ],
}

/** Expandable checkbox tree for picking sites, spaces, repos or folders. */
export function ScopeTree({ nodes, checked, onToggle, depth = 0 }: { nodes: TreeNode[]; checked: string[]; onToggle: (id: string, on: boolean) => void; depth?: number }) {
  const [open, setOpen] = React.useState<Record<string, boolean>>(() => Object.fromEntries(nodes.map((n) => [n.id, depth < 1])))
  return (
    <ul className={cn(depth > 0 && 'ml-5 border-l pl-2')}>
      {nodes.map((n) => {
        const hasKids = !!n.children?.length
        const isOpen = open[n.id]
        return (
          <li key={n.id}>
            <div className='flex items-center gap-1.5 rounded px-1 py-1 text-sm hover:bg-accent/60'>
              {hasKids ? (
                <button type='button' onClick={() => setOpen((o) => ({ ...o, [n.id]: !o[n.id] }))} className='rounded p-0.5 text-muted-foreground' aria-label={isOpen ? 'Collapse' : 'Expand'}>
                  {isOpen ? <ChevronDown className='size-3.5' /> : <ChevronRight className='size-3.5' />}
                </button>
              ) : (
                <span className='w-[18px]' />
              )}
              <Checkbox checked={checked.includes(n.id)} onCheckedChange={(v) => onToggle(n.id, !!v)} id={`node-${n.id}`} />
              {n.kind === 'folder' ? isOpen ? <FolderOpen className='size-4 text-muted-foreground' /> : <Folder className='size-4 text-muted-foreground' /> : <FileText className='size-4 text-muted-foreground' />}
              <label htmlFor={`node-${n.id}`} className='flex-1 cursor-pointer truncate'>{n.label}</label>
              {n.count !== undefined && <span className='text-xs tabular-nums text-muted-foreground'>{n.count.toLocaleString()}</span>}
            </div>
            {hasKids && isOpen && <ScopeTree nodes={n.children!} checked={checked} onToggle={onToggle} depth={depth + 1} />}
          </li>
        )
      })}
    </ul>
  )
}

/** Items under the checked nodes, counting a checked parent once for all its children. */
export function countFor(nodes: TreeNode[], ids: string[]): number {
  let n = 0
  const walk = (list: TreeNode[], parentChecked: boolean) => {
    for (const node of list) {
      const on = parentChecked || ids.includes(node.id)
      if (on && node.count) n += node.count
      if (node.children) walk(node.children, on)
    }
  }
  walk(nodes, false)
  return n
}
