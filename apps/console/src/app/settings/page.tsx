'use client';

import { SETTINGS_NAV, SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { Row, Rows, Section } from '@/components/shared/surface';
import { useTeam } from '@/hooks/use-team';

export default function SettingsPage() {
  const { team } = useTeam();
  return (
    <SettingsPageLayout section={team ? `${team.name} settings` : 'Settings'} description={team?.scope === 'all' ? 'Platform sees members and usage for every team.' : 'Changes here apply to this team only.'}>
      <Section flush>
        <Rows>
          {SETTINGS_NAV.map((s) => (
            <Row key={s.id} href={s.href} leading={<s.icon className="size-4 text-muted-foreground" />} title={s.title} description={s.description} />
          ))}
        </Rows>
      </Section>
    </SettingsPageLayout>
  );
}
