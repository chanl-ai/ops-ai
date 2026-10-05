'use client';

import { ReactNode } from 'react';
import { ExternalLink, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface SettingsSectionProps {
  /** Section title */
  title: string;
  /** Optional description shown below title */
  description?: string;
  /** Optional help text shown in tooltip */
  helpText?: string;
  /** Optional help link URL */
  helpLink?: string;
  /** Optional help link label (defaults to "Learn more") */
  helpLinkLabel?: string;
  /** Section content (form fields) */
  children: ReactNode;
  /** Additional class names */
  className?: string;
}

/**
 * Reusable settings section component with title, optional help, and styled container
 *
 * @example
 * ```tsx
 * <SettingsSection
 *   title="Vision Processing"
 *   description="Extract text from images using AI"
 *   helpText="Vision uses GPT-4o to analyze images. Additional costs apply."
 *   helpLink="https://docs.example.com/vision"
 * >
 *   <div className="flex items-center justify-between">
 *     <Label>Enable Vision</Label>
 *     <Switch checked={enabled} onCheckedChange={setEnabled} />
 *   </div>
 * </SettingsSection>
 * ```
 */
export function SettingsSection({
  title,
  description,
  helpText,
  helpLink,
  helpLinkLabel = 'Learn more',
  children,
  className,
}: SettingsSectionProps) {
  return (
    <div className={cn('rounded-lg border bg-muted/30 p-4', className)}>
      {/* Header */}
      <div className="mb-3">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-medium">{title}</h4>
          {helpText && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <HelpCircle className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs">
                  <p className="text-xs">{helpText}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          {helpLink && (
            <a
              href={helpLink}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {helpLinkLabel}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      </div>

      {/* Content */}
      <div className="space-y-3">{children}</div>
    </div>
  );
}

interface SettingsFieldProps {
  /** Field label */
  label: string;
  /** Optional description shown below label */
  description?: string;
  /** The form control (Switch, Input, Select, etc.) */
  children: ReactNode;
  /** HTML id for the form control */
  htmlFor?: string;
  /** Additional class names */
  className?: string;
}

/**
 * Individual settings field with label and description
 *
 * @example
 * ```tsx
 * <SettingsField
 *   label="Enable Vision"
 *   description="Process images with GPT-4o"
 *   htmlFor="vision-enabled"
 * >
 *   <Switch id="vision-enabled" checked={enabled} onCheckedChange={setEnabled} />
 * </SettingsField>
 * ```
 */
export function SettingsField({
  label,
  description,
  children,
  htmlFor,
  className,
}: SettingsFieldProps) {
  return (
    <div className={cn('flex items-center justify-between', className)}>
      <div className="space-y-0.5">
        <label htmlFor={htmlFor} className="text-sm font-normal cursor-pointer">
          {label}
        </label>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}
