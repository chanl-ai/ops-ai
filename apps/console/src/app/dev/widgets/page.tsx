'use client';

import { Shapes } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';

import type { LayoutPart, WidgetPart } from '@/lib/types/widgets';

// The same parts uc-073 reads and uc-061 will replay through the real chat stream, so all three draw identical data.
import parts from '@/lib/widgets/sample-parts.json';
// Filled widget templates and one composed layout, as agents-service sends them.
import layouts from '@/lib/widgets/sample-layouts.json';

import { WidgetGallery } from './widget-gallery';

/** A test surface for the chat widgets: one sample part per shape. Reachable only where src/proxy.ts lets /dev through, and not in the nav. */
export default function WidgetsPage() {
  return (
    <PageLayout icon={Shapes} title="Widget samples" description="Every widget shape with its sample data, drawn by the chat's renderers.">
      <WidgetGallery parts={parts as unknown as WidgetPart[]} layouts={layouts as unknown as LayoutPart[]} />
    </PageLayout>
  );
}
