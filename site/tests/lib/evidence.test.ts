import { describe, it, expect } from 'vitest';
import { humanizeField } from '../../src/lib/evidence';

describe('humanizeField', () => {
  it('turns agent_a / agent_b into "Agent A" / "Agent B"', () => {
    expect(humanizeField('agent_a.data_classes_touched')).toBe('Agent A · Data classes touched');
    expect(humanizeField('agent_b.data_classes_touched')).toBe('Agent B · Data classes touched');
  });

  it('keeps known acronyms uppercase', () => {
    expect(humanizeField('agent_b.io_surfaces.files')).toBe('Agent B · IO surfaces · Files');
    expect(humanizeField('agent_b.capabilities.use_mcp')).toBe('Agent B · Capabilities · Use MCP');
  });

  it('reads a long snake_case tail as a sentence', () => {
    expect(humanizeField('agent_a.concurrency_model.shared_state_with_other_instances')).toBe(
      'Agent A · Concurrency model · Shared state with other instances'
    );
    expect(humanizeField('agent_a.capabilities.network_egress')).toBe(
      'Agent A · Capabilities · Network egress'
    );
  });

  it('handles empty / undefined input', () => {
    expect(humanizeField(undefined)).toBe('');
    expect(humanizeField('')).toBe('');
  });
});
