import type { FilePurpose } from '@/lib/types/files';

/** The purposes files-service stores (the files contract's purpose enum); the Storage page sets a target for each. */
export const STORED_PURPOSES: FilePurpose[] = ['knowledge_source', 'chat_attachment', 'case_attachment', 'document_type_sample', 'email_body', 'test_import', 'evidence_bundle', 'export', 'tool_spec', 'avatar'];

export const PURPOSE_LABEL: Record<FilePurpose, string> = {
  knowledge_source: 'Knowledge source',
  chat_attachment: 'Chat attachment',
  case_attachment: 'Email attachment',
  document_type_sample: 'Document type sample',
  email_body: 'Email body',
  test_import: 'Test import',
  evidence_bundle: 'Evidence bundle',
  export: 'Export',
  tool_spec: 'Tool spec',
  avatar: 'Logo or avatar',
  skill_resource: 'Skill resource',
  idp_metadata: 'SSO metadata',
};
