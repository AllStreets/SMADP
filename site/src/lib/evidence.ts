// Turn a raw profile-field path (e.g. "agent_a.io_surfaces.files") into a
// readable provenance label (e.g. "Agent A · IO surfaces · Files") for the
// verdict-page Evidence section. The raw dotted/underscored form reads as
// debug output; this makes it presentable.

const ACRONYMS = new Set([
  'io', 'mcp', 'api', 'url', 'cpu', 'gpu', 'llm', 'id', 'ip', 'os',
  'sdk', 'ui', 'ux', 'db', 'http', 'https', 'json', 'yaml', 'pii', 'rag',
]);

function humanizeSegment(seg: string): string {
  // agent_a / agent_b -> Agent A / Agent B
  const agent = seg.match(/^agent_([a-z])$/i);
  if (agent) return `Agent ${agent[1].toUpperCase()}`;

  const phrase = seg
    .split('_')
    .map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w.toLowerCase()))
    .join(' ');

  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

export function humanizeField(field?: string): string {
  if (!field) return '';
  return field.split('.').map(humanizeSegment).join(' · ');
}
