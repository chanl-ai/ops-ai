import { DocsBody, DocsPage, DocsTitle } from 'fumadocs-ui/page';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { APIPage } from '@/components/api-page';
import { getMDXComponents } from '@/components/mdx';
import { REF, REPO } from '@/lib/repo.mjs';
import { source } from '@/lib/source';

type Props = { params: Promise<{ slug?: string[] }> };

export default async function Page({ params }: Props) {
  const { slug } = await params;
  const page = source.getPage(slug);
  if (!page) notFound();
  const data = page.data as typeof page.data & {
    getOpenAPIPageProps?: () => Record<string, unknown>;
    body?: React.ComponentType<{ components: ReturnType<typeof getMDXComponents> }>;
  };
  const service = page.path.split('/')[1];
  // An API page carries its service's document in its props, read from services/<service>/openapi.json.
  const apiProps = data.getOpenAPIPageProps?.();
  const [owner, repo] = REPO.split('/');
  // The file this page is read from: the markdown in docs/, or the service's openapi.json.
  const file = apiProps ? `services/${service}/openapi.json` : `docs/${page.path}`;

  return (
    <DocsPage
      toc={data.toc}
      editOnGithub={{ owner, repo, sha: REF, path: file }}
      className="ops-page"
    >
      <DocsTitle>{data.title}</DocsTitle>
      <DocsBody className="ops-prose">
        {apiProps ? (
          <APIPage {...(apiProps as Parameters<typeof APIPage>[0])} />
        ) : data.body ? (
          <data.body components={getMDXComponents()} />
        ) : null}
      </DocsBody>
    </DocsPage>
  );
}

export const dynamicParams = false;

export function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = source.getPage(slug);
  if (!page) notFound();
  return { title: page.data.title, description: page.data.description };
}
