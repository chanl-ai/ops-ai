'use client';

import Link from 'next/link';
import { Paperclip } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { dateTime, initials } from '@/lib/format';
import { cn } from '@/lib/utils';

export type EmailAttachment = {
  name: string;
  href?: string;
  type?: string | null;
  size?: number | null;
};

export type EmailPreviewProps = {
  from?: string | null;
  to?: string | null;
  subject?: string | null;
  date?: string | null;
  body?: string | null;
  html?: string | null;
  attachments?: EmailAttachment[];
  /** A short caption above the card ("The reply", "Received"). */
  label?: string;
  /** Wrapper test id; From / To / Subject / body use `${testId}-from` and so on. */
  testId?: string;
  className?: string;
};

const ALLOWED = new Set(['P', 'BR', 'DIV', 'SPAN', 'STRONG', 'EM', 'B', 'I', 'U', 'A', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'PRE', 'CODE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6']);

/** Safe markup for an HTML body: only the tags an email client shows, and http, https or mailto links. */
export function sanitizeEmailHtml(html: string): string {
  if (typeof DOMParser === 'undefined') return '';
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const walk = (node: Node) => {
    [...node.childNodes].forEach((child) => {
      if (child.nodeType === Node.COMMENT_NODE) {
        child.parentNode?.removeChild(child);
        return;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const el = child as Element;
      if (!ALLOWED.has(el.tagName)) {
        el.replaceWith(doc.createTextNode(el.textContent ?? ''));
        return;
      }
      [...el.attributes].forEach((attr) => {
        if (el.tagName === 'A' && attr.name === 'href' && /^(https?:|mailto:)/i.test(attr.value)) return;
        el.removeAttribute(attr.name);
      });
      if (el.tagName === 'A') el.setAttribute('rel', 'noreferrer noopener');
      walk(el);
    });
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

function looksLikeHtml(value: string): boolean {
  return /<[a-z][\s\S]*>/i.test(value);
}

function senderLabel(from: string): string {
  const named = from.match(/^\s*([^<]+?)\s*</);
  if (named?.[1] && !named[1].includes('@')) return named[1].trim();
  return from.trim();
}

function senderInitials(from: string): string {
  const label = senderLabel(from);
  if (!label.includes('@')) return initials(label) || '?';
  const local = label.split('@')[0]?.replace(/[+._-].*$/, '') ?? '';
  return initials(local.replace(/[^A-Za-z\s]/g, ' ')) || label.slice(0, 2).toUpperCase() || '?';
}

function shownDate(value?: string | null): string | undefined {
  if (!value) return undefined;
  return Number.isNaN(Date.parse(value)) ? value : dateTime(value);
}

function Line({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="flex min-w-0 gap-2 text-sm">
      <span className="w-14 shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words font-medium" data-testid={testId}>
        {value}
      </span>
    </div>
  );
}

/**
 * An email as a mail client shows it: avatar, From / To / Subject / date, then the body.
 * Plain text keeps its line breaks; HTML is sanitised. Used on Human Tasks, the run page and a reply preview.
 */
export function EmailPreview({ from, to, subject, date, body, html, attachments, label, testId = 'email', className }: EmailPreviewProps) {
  const fromText = from?.trim() || '';
  const toText = to?.trim() || '';
  const subjectText = subject?.trim() || 'No subject';
  const markup = html?.trim() || (body && looksLikeHtml(body) ? body : '');
  const safeHtml = markup ? sanitizeEmailHtml(markup) : '';
  const plain = (body ?? '').trim();
  const when = shownDate(date);
  return (
    <div className={cn('flex min-w-0 flex-col gap-2', className)} data-testid={testId}>
      {label && <p className="text-xs font-medium text-muted-foreground">{label}</p>}
      <Card className="gap-0 py-0">
        <CardHeader className="flex flex-col gap-3 px-4 pt-4 sm:flex-row sm:items-start">
          <Avatar className="size-8" aria-hidden>
            <AvatarFallback>{fromText ? senderInitials(fromText) : '?'}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            {fromText && <Line label="From" value={fromText} testId={`${testId}-from`} />}
            {toText && <Line label="To" value={toText} testId={`${testId}-to`} />}
            <Line label="Subject" value={subjectText} testId={`${testId}-subject`} />
          </div>
          {when && (
            <time className="shrink-0 text-xs text-muted-foreground" dateTime={date ?? undefined}>
              {when}
            </time>
          )}
        </CardHeader>
        <Separator />
        <CardContent className="flex flex-col gap-3 px-4 py-4">
          {safeHtml ? (
            <div className="max-h-64 overflow-y-auto text-sm break-words [&_a]:underline" data-testid={`${testId}-body`} dangerouslySetInnerHTML={{ __html: safeHtml }} />
          ) : (
            <p className="max-h-64 overflow-y-auto text-sm break-words whitespace-pre-wrap" data-testid={`${testId}-body`}>
              {plain || <span className="text-muted-foreground">The email had no text.</span>}
            </p>
          )}
          {!!attachments?.length && (
            <div className="flex flex-wrap gap-1.5" data-testid={`${testId}-attachments`}>
              {attachments.map((a) => {
                const chip = (
                  <Badge variant="outline" className="max-w-full font-normal">
                    <Paperclip />
                    <span className="truncate">{a.name}</span>
                  </Badge>
                );
                return a.href ? (
                  <Link key={`${a.href}-${a.name}`} href={a.href} className="min-w-0">
                    {chip}
                  </Link>
                ) : (
                  <span key={a.name} className="min-w-0">
                    {chip}
                  </span>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
