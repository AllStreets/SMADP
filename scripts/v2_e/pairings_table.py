"""Authoritative pairings table for the v2-E catalog (100 profiles).

Symmetry: if A → B is listed, the backfill script also writes B → A.
Lint enforces this at validate-time.
"""

from __future__ import annotations

# Edge list — directional only by listing convention; backfill makes it symmetric.
PAIRS: list[tuple[str, str]] = [
    # IDE coding-with-coding clusters
    ("claude-code", "cursor"),
    ("claude-code", "windsurf"),
    ("claude-code", "github-copilot"),
    ("claude-code", "aider"),
    ("claude-code", "cline"),
    ("cursor", "github-copilot"),
    ("cursor", "windsurf"),
    ("cursor", "supermaven"),
    ("cursor", "tabnine"),
    ("cursor", "codeium"),
    ("github-copilot", "tabnine"),
    ("github-copilot", "codeium"),
    ("aider", "continue-dev"),
    ("continue-dev", "github-copilot"),
    ("cline", "roo-cline"),
    ("openhands", "swe-agent"),
    ("openhands", "claude-code"),
    ("swe-agent", "aider"),
    ("devin", "claude-code"),
    ("plandex", "aider"),
    ("mentat", "aider"),
    ("gpt-engineer", "smol-developer"),
    ("pythagora", "cursor"),
    ("double-chat", "cursor"),
    ("qodo", "github-copilot"),
    ("goose", "cursor"),
    # Web/app builders
    ("bolt-new", "v0-by-vercel"),
    ("v0-by-vercel", "lovable"),
    ("bolt-new", "claude-code"),
    ("builder-io-visual-copilot", "v0-by-vercel"),
    # Frameworks / orchestration
    ("autogen", "crewai"),
    ("autogen", "langgraph"),
    ("crewai", "langgraph"),
    ("langgraph", "smolagents"),
    ("smolagents", "openai-swarm"),
    ("openai-swarm", "llama-agents"),
    ("microsoft-magentic", "autogen"),
    ("semantic-kernel", "langgraph"),
    ("langflow", "flowise"),
    ("dify", "flowise"),
    ("dify", "langflow"),
    ("n8n", "dify"),
    # RAG / search
    ("perplexity", "claude-code"),
    ("perplexity", "you-com"),
    ("you-com", "exa-search"),
    ("exa-search", "claude-code"),
    ("glean", "perplexity"),
    ("kapa-ai", "glean"),
    ("khoj", "claude-code"),
    # Browser / OS
    ("browser-use", "playwright-mcp"),
    ("playwright-mcp", "claude-code"),
    ("multion", "browser-use"),
    ("openai-operator", "anthropic-computer-use"),
    ("anthropic-computer-use", "simular-agent-s"),
    # Data / analytics
    ("vanna-ai", "textql"),
    ("textql", "claude-code"),
    ("julius-ai", "claude-code"),
    ("rows-ai", "claude-code"),
    ("meltano-ai", "claude-code"),
    # Docs / writing / email
    ("notion-ai", "claude-code"),
    ("docling", "unstructured-io"),
    ("unstructured-io", "khoj"),
    ("jasper", "copy-ai"),
    ("copy-ai", "anyword"),
    ("descript", "elevenlabs"),
    ("superhuman-ai", "motion-ai"),
    ("motion-ai", "reclaim-ai"),
    # Image / video / audio
    ("midjourney", "dall-e-3"),
    ("dall-e-3", "stable-diffusion-xl"),
    ("stable-diffusion-xl", "flux-schnell"),
    ("runway-gen3", "pika-labs"),
    ("suno", "elevenlabs"),
    # Devops / security
    ("pulumi-ai", "k8sgpt"),
    ("k8sgpt", "claude-code"),
    ("pentestgpt", "garak"),
    ("garak", "promptfoo"),
    ("promptfoo", "claude-code"),
    # Vertical / SaaS
    ("harvey-ai", "casetext-cocounsel"),
    ("casetext-cocounsel", "lexis-protege"),
    ("intercom-fin", "ada-cx"),
    ("nuance-dax", "abridge"),
    ("clay-agent", "perplexity"),
    ("anyword", "jasper"),
    ("house-canary-ai", "textql"),
    # Knowledge / reasoning / tutoring / science
    ("mem-ai", "notion-ai"),
    ("khanmigo", "magic-school"),
    ("wolfram-llm", "claude-code"),
    ("elicit", "scispace"),
    ("scispace", "perplexity"),
    ("alphafold-server", "elicit"),
    ("causal-ai", "rows-ai"),
    ("deepl-write", "jasper"),
    # Cross-cluster bridges (ensure no orphan slugs)
    ("chatgpt-desktop", "perplexity"),
    ("chatgpt-desktop", "cursor"),
    ("gemini-cli", "cursor"),
    ("replit-agent", "cursor"),
    ("replit-agent", "bolt-new"),
    ("open-interpreter", "perplexity"),
    # Sandbox test fixture: paired with aider so the smoke set has a valid
    # capability-binding pair. Not a real production pairing.
    ("aider", "synthetic-adapter"),
]


def build_table(pairs: list[tuple[str, str]] | None = None) -> dict[str, list[str]]:
    src = pairs or PAIRS
    table: dict[str, list[str]] = {}
    for a, b in src:
        if a == b:
            raise ValueError(f"self-pair {a!r}")
        table.setdefault(a, [])
        table.setdefault(b, [])
        if b not in table[a]:
            table[a].append(b)
        if a not in table[b]:
            table[b].append(a)
    for slug in table:
        table[slug].sort()
    return table


__all__ = ["PAIRS", "build_table"]
