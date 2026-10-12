import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { dateTime, pct, plural } from '@/lib/format';
import type { AssuranceJudge } from '@/lib/types/assurance';

import { OutcomeText } from './assurance-meta';

/** A judge's calibration and the cases where its verdict and a reviewer's label disagree. */
export function JudgeSheet({ judge, open, onOpenChange, navigation }: { judge: AssuranceJudge | null; open: boolean; onOpenChange: (o: boolean) => void; navigation?: DetailSheetNavigation }) {
  const j = judge;
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} testId="judge-sheet" scrollKey={j?.id} navigation={navigation} title={j?.name ?? ''} description={j?.criterion}>
      {j && (
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-1">
            <FieldRow label="Judge model" value={<code className="font-mono text-xs">{j.model}</code>} />
            <FieldRow label="Prompt" value={`v${j.promptVersion}`} />
            <FieldRow label="Calibration set" value={plural(j.calibrationSize, 'labelled case')} />
            <FieldRow label="Agreement" value={`${pct(j.agreement)}${j.agreement < j.minAgreement ? ` · below ${pct(j.minAgreement)}, so its verdicts are advisory` : ''}`} />
            <FieldRow label="Last recalibrated" value={dateTime(j.lastRecalibratedAt)} />
          </section>
          <section className="flex flex-col gap-2">
            <FieldSectionLabel>Disagreements · {j.disagreements.length}</FieldSectionLabel>
            {j.disagreements.length ? (
              <ul className="flex flex-col gap-2">
                {j.disagreements.map((d) => (
                  <li key={d.id} className="rounded-lg border p-3 text-sm">
                    <div className="font-medium">{d.caseName}</div>
                    <div className="text-xs text-muted-foreground">{d.assetName}</div>
                    <div className="mt-2 flex gap-4 text-xs">
                      <span>Judge <OutcomeText outcome={d.judge} /></span>
                      <span>{d.reviewer} <OutcomeText outcome={d.human} /></span>
                    </div>
                    <p className="mt-1 text-muted-foreground">{d.note}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">The judge agrees with every reviewer label in its calibration set.</p>
            )}
          </section>
        </div>
      )}
    </DetailSheet>
  );
}
