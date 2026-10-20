'use client';


import { createOpenAPIPage } from 'fumadocs-openapi/ui';

// No playground: this site is not an Ops AI server, so a Send button would only reach the docs host.
export const APIPage = createOpenAPIPage({ playground: { enabled: false } });
