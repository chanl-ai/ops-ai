import { toast } from 'sonner';

/** What Save does in the mock: say so, store nothing. */
export function mockSave(what: string): void {
  toast.success(`${what} saved`, { description: 'Design mock: nothing was stored.' });
}
