import type { PersonaId } from './session';

export const PANEL_KEYS = [
  'exec_summary',
  'deployments',
  'framework_coverage',
  'refresh_freshness',
  'disputes',
  'transparency',
  'vendor_responses',
  'webhooks',
  'passports',
] as const;

export type PanelKey = (typeof PANEL_KEYS)[number];

export interface PersonaSpec {
  id: PersonaId;
  name: string;
  tagline: string;
  panels: PanelKey[];
}

export const PERSONAS: readonly PersonaSpec[] = [
  {
    id: 'auditor',
    name: 'External auditor',
    tagline: 'Tamper-evident evidence, mapped to controls.',
    panels: ['framework_coverage', 'passports', 'transparency', 'disputes'],
  },
  {
    id: 'procurement',
    name: 'Vendor-risk / procurement',
    tagline: 'Cross-vendor packets, framework cross-walks, questionnaire pre-fills.',
    panels: ['deployments', 'framework_coverage', 'vendor_responses', 'passports'],
  },
  {
    id: 'grc',
    name: 'Internal compliance / GRC',
    tagline: 'Portfolio of deployed agents with continuous freshness.',
    panels: ['deployments', 'refresh_freshness', 'disputes', 'webhooks'],
  },
  {
    id: 'ciso',
    name: 'CISO / exec buyer',
    tagline: 'One-page risk summary with traffic-light verdicts.',
    panels: ['exec_summary', 'framework_coverage', 'refresh_freshness', 'webhooks'],
  },
];

const BY_ID = new Map(PERSONAS.map((p) => [p.id, p] as const));

export function getPersonaSpec(id: PersonaId): PersonaSpec {
  const p = BY_ID.get(id);
  if (!p) throw new Error(`unknown persona: ${id}`);
  return p;
}
