'use client';

import { DialogShell } from '@/components/shared/dialog-shell';
import { CopyButton } from '@/components/shared/copy-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * The links of the invitations just sent. No email goes out, and the service keeps only a hash of each link, so this is
 * the one time an admin can copy them; a lost link is replaced by removing the invite and inviting again.
 */
export function InviteLinksDialog({ links, onClose }: { links: { email: string; url: string }[]; onClose: () => void }) {
  return (
    <DialogShell
      open={links.length > 0}
      onOpenChange={(o) => !o && onClose()}
      size="md"
      title={links.length === 1 ? 'Send this invitation link' : `Send these ${links.length} invitation links`}
      description="Shown once. Each link works for its email address, once, for 7 days."
      footer={
        <div className="flex w-full justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-testid="invite-links">
        {links.map((l) => (
          <div key={l.email} className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{l.email}</span>
            <div className="flex items-center gap-2">
              <Input readOnly value={l.url} aria-label={`Invitation link for ${l.email}`} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
              <CopyButton text={l.url} variant="outline" />
            </div>
          </div>
        ))}
      </div>
    </DialogShell>
  );
}
