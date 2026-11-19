// The one folder a use case writes into. harness.ts's evidenceDir() and the runner's own logs both resolve here, so a
// run leaves nothing outside it. scripts/check_usecase_outputs.py fails a use-case script that writes anywhere else.
import { join } from 'node:path';

/** OPS_EVIDENCE_DIR, else .logs/usecases/ in the tree (ignored by git). */
export function evidenceRoot(root: string): string {
  return process.env.OPS_EVIDENCE_DIR ?? join(root, '.logs', 'usecases');
}

/** A case's folder under the root. A leading `uc-` is dropped, so the runner's `uc-224` and a script's `224` are one folder. */
export function caseDir(root: string, id: string, ...parts: string[]): string {
  return join(evidenceRoot(root), id.replace(/^uc-/, ''), ...parts);
}
