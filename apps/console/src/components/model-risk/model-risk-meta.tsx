'use client';

import { Badge } from '@/components/ui/badge';
import type { ConditionStatus, FindingSeverity, FindingStatus, ValidationStatus } from '@/lib/types/model-risk';
import { cn } from '@/lib/utils';

export const VALIDATION_STATUS_LABEL: Record<ValidationStatus, string> = {
  not_validated: 'Not validated',
  in_validation: 'In validation',
  validated: 'Validated',
  validated_with_conditions: 'Validated with conditions',
  expired: 'Expired',
};

const VALIDATION_TONE: Record<ValidationStatus, string> = {
  not_validated: 'border-amber-300 text-amber-800 dark:border-amber-900 dark:text-amber-300',
  in_validation: 'border-sky-300 text-sky-800 dark:border-sky-900 dark:text-sky-300',
  validated: 'border-emerald-300 text-emerald-800 dark:border-emerald-900 dark:text-emerald-300',
  validated_with_conditions: 'border-emerald-300 text-emerald-800 dark:border-emerald-900 dark:text-emerald-300',
  expired: 'border-red-300 text-red-700 dark:border-red-900 dark:text-red-300',
};

/** `wrap` lets a long label ("Validated with conditions") break onto two lines in a narrow table column. */
export function ValidationBadge({ status, wrap }: { status: ValidationStatus; wrap?: boolean }) {
  return (
    <Badge variant="outline" className={cn('font-normal', wrap ? 'h-auto text-left whitespace-normal' : 'whitespace-nowrap', VALIDATION_TONE[status])}>
      {VALIDATION_STATUS_LABEL[status]}
    </Badge>
  );
}

const SEVERITY_TONE: Record<FindingSeverity, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  low: 'bg-muted text-muted-foreground',
};

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
  return <Badge className={cn('capitalize', SEVERITY_TONE[severity])}>{severity}</Badge>;
}

export const FINDING_STATUS_LABEL: Record<FindingStatus, string> = { open: 'Open', remediating: 'Remediating', closed: 'Closed' };
export const CONDITION_STATUS_LABEL: Record<ConditionStatus, string> = { open: 'Open', met: 'Met', overdue: 'Overdue' };

export function ConditionBadge({ status }: { status: ConditionStatus }) {
  return (
    <Badge variant="outline" className={cn('font-normal', status === 'overdue' && 'border-red-300 text-red-700 dark:border-red-900 dark:text-red-300', status === 'met' && 'text-muted-foreground')}>
      {CONDITION_STATUS_LABEL[status]}
    </Badge>
  );
}

export const TYPE_LABEL = { agent: 'Agent', workflow: 'Workflow' } as const;
