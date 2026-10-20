'use client';

import * as React from 'react';
import { format, subDays, startOfDay, endOfDay } from 'date-fns';
import { CalendarIcon } from 'lucide-react';
import { type DateRange } from 'react-day-picker';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export interface DateRangePickerProps {
  value?: DateRange;
  onChange: (range: DateRange | undefined) => void;
  className?: string;
  placeholder?: string;
  align?: 'start' | 'center' | 'end';
  /** Show preset buttons (Last 7 days, Last 30 days, etc.) */
  showPresets?: boolean;
}

const PRESETS = [
  { label: 'Today', from: () => startOfDay(new Date()), to: () => endOfDay(new Date()) },
  { label: 'Last 7 days', from: () => subDays(new Date(), 7), to: () => new Date() },
  { label: 'Last 30 days', from: () => subDays(new Date(), 30), to: () => new Date() },
  { label: 'Last 90 days', from: () => subDays(new Date(), 90), to: () => new Date() },
] as const;

export function DateRangePicker({
  value,
  onChange,
  className,
  placeholder = 'Pick a date range',
  align = 'start',
  showPresets = true,
}: DateRangePickerProps) {
  const [open, setOpen] = React.useState(false);

  const handlePreset = (preset: (typeof PRESETS)[number]) => {
    onChange({ from: preset.from(), to: preset.to() });
    setOpen(false);
  };

  return (
    <div className={cn('grid gap-2', className)}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className={cn(
              'h-8 justify-start text-left font-normal border-dashed',
              !value?.from && 'text-muted-foreground'
            )}
            data-testid="date-range-picker-trigger"
          >
            <CalendarIcon className="mr-2 h-3.5 w-3.5" />
            {value?.from ? (
              value.to ? (
                <>
                  {format(value.from, 'MMM d, yyyy')} – {format(value.to, 'MMM d, yyyy')}
                </>
              ) : (
                format(value.from, 'MMM d, yyyy')
              )
            ) : (
              <span>{placeholder}</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align={align}>
          <div className="flex">
            {showPresets && (
              <div className="flex flex-col gap-1 border-r p-3">
                {PRESETS.map((preset) => (
                  <Button
                    key={preset.label}
                    variant="ghost"
                    size="sm"
                    className="h-7 justify-start text-xs"
                    onClick={() => handlePreset(preset)}
                    data-testid={`date-preset-${preset.label.toLowerCase().replace(/\s+/g, '-')}`}
                  >
                    {preset.label}
                  </Button>
                ))}
              </div>
            )}
            <Calendar
              initialFocus
              mode="range"
              defaultMonth={value?.from}
              selected={value}
              onSelect={onChange}
              numberOfMonths={2}
            />
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
