"""SMADP v2-E ontology: 70 net-new agent profiles + per-category capability presets."""

from __future__ import annotations

from typing import TypedDict


class Seed(TypedDict):
    slug: str
    name: str
    vendor_handle: str
    vendor_type: str
    source_type: str
    category: str
    homepage: str | None
    repo_url: str | None
    tagline: str


SEEDS: list[Seed] = [
    # ----- coding (10)
    {"slug": "bolt-new", "name": "Bolt.new", "vendor_handle": "StackBlitz", "vendor_type": "company", "source_type": "closed-source", "category": "web-dev", "homepage": "https://bolt.new", "repo_url": None, "tagline": "Browser-based AI app builder with live preview."},
    {"slug": "v0-by-vercel", "name": "v0", "vendor_handle": "Vercel", "vendor_type": "company", "source_type": "closed-source", "category": "web-dev", "homepage": "https://v0.dev", "repo_url": None, "tagline": "Generative UI for React + Tailwind."},
    {"slug": "lovable", "name": "Lovable", "vendor_handle": "Lovable.dev", "vendor_type": "company", "source_type": "closed-source", "category": "web-dev", "homepage": "https://lovable.dev", "repo_url": None, "tagline": "Full-stack web app generator from prompts."},
    {"slug": "supermaven", "name": "Supermaven", "vendor_handle": "Supermaven", "vendor_type": "company", "source_type": "closed-source", "category": "coding", "homepage": "https://supermaven.com", "repo_url": None, "tagline": "Million-token-context code completion."},
    {"slug": "codeium", "name": "Codeium", "vendor_handle": "Codeium", "vendor_type": "company", "source_type": "closed-source", "category": "coding", "homepage": "https://codeium.com", "repo_url": None, "tagline": "Free AI autocomplete + chat for IDEs."},
    {"slug": "tabnine", "name": "Tabnine", "vendor_handle": "Tabnine", "vendor_type": "company", "source_type": "closed-source", "category": "coding", "homepage": "https://tabnine.com", "repo_url": None, "tagline": "Privacy-first code completion."},
    {"slug": "qodo", "name": "Qodo (Codium)", "vendor_handle": "Qodo", "vendor_type": "company", "source_type": "closed-source", "category": "coding", "homepage": "https://qodo.ai", "repo_url": None, "tagline": "Test-driven code review and PR agent."},
    {"slug": "pythagora", "name": "Pythagora", "vendor_handle": "Pythagora", "vendor_type": "company", "source_type": "open-source", "category": "coding", "homepage": "https://pythagora.ai", "repo_url": "https://github.com/Pythagora-io/gpt-pilot", "tagline": "Autonomous full-app developer (GPT-Pilot)."},
    {"slug": "double-chat", "name": "Double", "vendor_handle": "Double", "vendor_type": "company", "source_type": "closed-source", "category": "coding", "homepage": "https://double.bot", "repo_url": None, "tagline": "VS Code AI extension by ex-Bain engineers."},
    {"slug": "smol-developer", "name": "smol-developer", "vendor_handle": "smol-ai", "vendor_type": "individual", "source_type": "open-source", "category": "coding", "homepage": None, "repo_url": "https://github.com/smol-ai/developer", "tagline": "Single-prompt junior dev that scaffolds projects."},
    # ----- web-dev / data (4)
    {"slug": "builder-io-visual-copilot", "name": "Builder.io Visual Copilot", "vendor_handle": "Builder.io", "vendor_type": "company", "source_type": "closed-source", "category": "web-dev", "homepage": "https://builder.io", "repo_url": None, "tagline": "Figma-to-code with framework awareness."},
    {"slug": "meltano-ai", "name": "Meltano AI", "vendor_handle": "Meltano", "vendor_type": "company", "source_type": "open-source", "category": "data-engineering", "homepage": "https://meltano.com", "repo_url": "https://github.com/meltano/meltano", "tagline": "AI-assisted ELT pipeline authoring."},
    {"slug": "julius-ai", "name": "Julius", "vendor_handle": "Julius", "vendor_type": "company", "source_type": "closed-source", "category": "data-science-ml", "homepage": "https://julius.ai", "repo_url": None, "tagline": "Natural-language data analyst with code execution."},
    {"slug": "causal-ai", "name": "Causal AI", "vendor_handle": "Causal", "vendor_type": "company", "source_type": "closed-source", "category": "financial-modeling", "homepage": "https://causal.app", "repo_url": None, "tagline": "Spreadsheet-native financial modelling agent."},
    # ----- legal / support / writing (8)
    {"slug": "harvey-ai", "name": "Harvey", "vendor_handle": "Harvey", "vendor_type": "company", "source_type": "closed-source", "category": "legal-research", "homepage": "https://harvey.ai", "repo_url": None, "tagline": "Generative AI for elite law firms."},
    {"slug": "casetext-cocounsel", "name": "CoCounsel", "vendor_handle": "Thomson Reuters", "vendor_type": "company", "source_type": "closed-source", "category": "legal-research", "homepage": "https://casetext.com", "repo_url": None, "tagline": "Legal research and document review assistant."},
    {"slug": "lexis-protege", "name": "Protégé", "vendor_handle": "LexisNexis", "vendor_type": "company", "source_type": "closed-source", "category": "legal-research", "homepage": "https://www.lexisnexis.com", "repo_url": None, "tagline": "Personalized legal AI assistant."},
    {"slug": "intercom-fin", "name": "Fin", "vendor_handle": "Intercom", "vendor_type": "company", "source_type": "closed-source", "category": "customer-support", "homepage": "https://intercom.com/fin", "repo_url": None, "tagline": "Tier-1 support resolution agent."},
    {"slug": "ada-cx", "name": "Ada", "vendor_handle": "Ada", "vendor_type": "company", "source_type": "closed-source", "category": "customer-support", "homepage": "https://ada.cx", "repo_url": None, "tagline": "Enterprise customer-service automation."},
    {"slug": "jasper", "name": "Jasper", "vendor_handle": "Jasper", "vendor_type": "company", "source_type": "closed-source", "category": "content-writing", "homepage": "https://jasper.ai", "repo_url": None, "tagline": "Brand-tuned long-form content generator."},
    {"slug": "copy-ai", "name": "Copy.ai", "vendor_handle": "Copy.ai", "vendor_type": "company", "source_type": "closed-source", "category": "content-writing", "homepage": "https://copy.ai", "repo_url": None, "tagline": "GTM workflow automation with content + research."},
    {"slug": "deepl-write", "name": "DeepL Write", "vendor_handle": "DeepL", "vendor_type": "company", "source_type": "closed-source", "category": "translation", "homepage": "https://deepl.com/write", "repo_url": None, "tagline": "AI writing improvement and translation."},
    # ----- image / video / audio (9)
    {"slug": "midjourney", "name": "Midjourney", "vendor_handle": "Midjourney", "vendor_type": "company", "source_type": "closed-source", "category": "image-generation", "homepage": "https://midjourney.com", "repo_url": None, "tagline": "Discord-native generative image platform."},
    {"slug": "dall-e-3", "name": "DALL·E 3", "vendor_handle": "OpenAI", "vendor_type": "company", "source_type": "closed-source", "category": "image-generation", "homepage": "https://openai.com/dall-e-3", "repo_url": None, "tagline": "OpenAI's text-to-image model."},
    {"slug": "stable-diffusion-xl", "name": "Stable Diffusion XL", "vendor_handle": "Stability AI", "vendor_type": "company", "source_type": "open-source", "category": "image-generation", "homepage": "https://stability.ai", "repo_url": "https://github.com/Stability-AI/generative-models", "tagline": "Open-weight diffusion image model."},
    {"slug": "flux-schnell", "name": "FLUX.1 schnell", "vendor_handle": "Black Forest Labs", "vendor_type": "company", "source_type": "open-source", "category": "image-generation", "homepage": "https://blackforestlabs.ai", "repo_url": "https://github.com/black-forest-labs/flux", "tagline": "Apache-2.0 fast diffusion model."},
    {"slug": "runway-gen3", "name": "Runway Gen-3", "vendor_handle": "Runway", "vendor_type": "company", "source_type": "closed-source", "category": "video-generation", "homepage": "https://runwayml.com", "repo_url": None, "tagline": "Text-to-video and video-to-video studio."},
    {"slug": "pika-labs", "name": "Pika", "vendor_handle": "Pika Labs", "vendor_type": "company", "source_type": "closed-source", "category": "video-generation", "homepage": "https://pika.art", "repo_url": None, "tagline": "Generative video with effect controls."},
    {"slug": "elevenlabs", "name": "ElevenLabs", "vendor_handle": "ElevenLabs", "vendor_type": "company", "source_type": "closed-source", "category": "audio-speech", "homepage": "https://elevenlabs.io", "repo_url": None, "tagline": "Voice cloning and TTS at scale."},
    {"slug": "suno", "name": "Suno", "vendor_handle": "Suno", "vendor_type": "company", "source_type": "closed-source", "category": "audio-speech", "homepage": "https://suno.com", "repo_url": None, "tagline": "Generative music and song creation."},
    {"slug": "descript", "name": "Descript", "vendor_handle": "Descript", "vendor_type": "company", "source_type": "closed-source", "category": "audio-speech", "homepage": "https://descript.com", "repo_url": None, "tagline": "Edit audio/video by editing the transcript."},
    # ----- search / browser / OS (10)
    {"slug": "glean", "name": "Glean Assistant", "vendor_handle": "Glean", "vendor_type": "company", "source_type": "closed-source", "category": "search-rag", "homepage": "https://glean.com", "repo_url": None, "tagline": "Enterprise search + agentic workplace assistant."},
    {"slug": "you-com", "name": "You.com", "vendor_handle": "You.com", "vendor_type": "company", "source_type": "closed-source", "category": "search-rag", "homepage": "https://you.com", "repo_url": None, "tagline": "Conversational search with citations."},
    {"slug": "exa-search", "name": "Exa", "vendor_handle": "Exa", "vendor_type": "company", "source_type": "closed-source", "category": "search-rag", "homepage": "https://exa.ai", "repo_url": None, "tagline": "Embedding-based search API for agents."},
    {"slug": "kapa-ai", "name": "Kapa", "vendor_handle": "Kapa.ai", "vendor_type": "company", "source_type": "closed-source", "category": "search-rag", "homepage": "https://kapa.ai", "repo_url": None, "tagline": "Docs-grounded answer bots for SaaS."},
    {"slug": "browser-use", "name": "Browser Use", "vendor_handle": "browser-use", "vendor_type": "org", "source_type": "open-source", "category": "browser-automation", "homepage": "https://browser-use.com", "repo_url": "https://github.com/browser-use/browser-use", "tagline": "Open-source agent runtime for the web."},
    {"slug": "playwright-mcp", "name": "Playwright MCP", "vendor_handle": "Microsoft", "vendor_type": "company", "source_type": "open-source", "category": "browser-automation", "homepage": "https://playwright.dev", "repo_url": "https://github.com/microsoft/playwright-mcp", "tagline": "MCP server for Playwright browser control."},
    {"slug": "multion", "name": "MultiOn", "vendor_handle": "MultiOn", "vendor_type": "company", "source_type": "closed-source", "category": "browser-automation", "homepage": "https://multion.ai", "repo_url": None, "tagline": "Web agent that operates a real browser."},
    {"slug": "simular-agent-s", "name": "Agent S", "vendor_handle": "Simular", "vendor_type": "company", "source_type": "open-source", "category": "desktop-os-automation", "homepage": "https://simular.ai", "repo_url": "https://github.com/simular-ai/Agent-S", "tagline": "GUI agent that uses your computer like a human."},
    {"slug": "anthropic-computer-use", "name": "Claude Computer Use", "vendor_handle": "Anthropic", "vendor_type": "company", "source_type": "closed-source", "category": "desktop-os-automation", "homepage": "https://www.anthropic.com", "repo_url": None, "tagline": "Claude controls a virtual desktop via screenshots."},
    {"slug": "openai-operator", "name": "Operator", "vendor_handle": "OpenAI", "vendor_type": "company", "source_type": "closed-source", "category": "browser-automation", "homepage": "https://openai.com", "repo_url": None, "tagline": "OpenAI's browser-using agent."},
    # ----- documents / email / sched (5)
    {"slug": "docling", "name": "Docling", "vendor_handle": "IBM Research", "vendor_type": "company", "source_type": "open-source", "category": "document-processing", "homepage": "https://github.com/DS4SD/docling", "repo_url": "https://github.com/DS4SD/docling", "tagline": "Document parsing and layout extraction."},
    {"slug": "unstructured-io", "name": "Unstructured", "vendor_handle": "Unstructured", "vendor_type": "company", "source_type": "open-source", "category": "document-processing", "homepage": "https://unstructured.io", "repo_url": "https://github.com/Unstructured-IO/unstructured", "tagline": "ETL for unstructured documents into LLM-ready data."},
    {"slug": "superhuman-ai", "name": "Superhuman AI", "vendor_handle": "Superhuman", "vendor_type": "company", "source_type": "closed-source", "category": "email-scheduling", "homepage": "https://superhuman.com", "repo_url": None, "tagline": "Inbox triage and reply drafting."},
    {"slug": "motion-ai", "name": "Motion", "vendor_handle": "Motion", "vendor_type": "company", "source_type": "closed-source", "category": "email-scheduling", "homepage": "https://usemotion.com", "repo_url": None, "tagline": "AI calendar that replans your day."},
    {"slug": "reclaim-ai", "name": "Reclaim", "vendor_handle": "Reclaim.ai", "vendor_type": "company", "source_type": "closed-source", "category": "email-scheduling", "homepage": "https://reclaim.ai", "repo_url": None, "tagline": "Time-block scheduling assistant."},
    # ----- devops / security (5)
    {"slug": "pulumi-ai", "name": "Pulumi AI", "vendor_handle": "Pulumi", "vendor_type": "company", "source_type": "closed-source", "category": "devops-sre", "homepage": "https://pulumi.com/ai", "repo_url": None, "tagline": "Natural-language infra-as-code generator."},
    {"slug": "k8sgpt", "name": "K8sGPT", "vendor_handle": "K8sGPT", "vendor_type": "org", "source_type": "open-source", "category": "devops-sre", "homepage": "https://k8sgpt.ai", "repo_url": "https://github.com/k8sgpt-ai/k8sgpt", "tagline": "Kubernetes diagnostics with LLM analysis."},
    {"slug": "pentestgpt", "name": "PentestGPT", "vendor_handle": "GreyDGL", "vendor_type": "individual", "source_type": "open-source", "category": "security-pentesting", "homepage": None, "repo_url": "https://github.com/GreyDGL/PentestGPT", "tagline": "GPT-driven pentest planning assistant."},
    {"slug": "garak", "name": "garak", "vendor_handle": "NVIDIA", "vendor_type": "company", "source_type": "open-source", "category": "security-pentesting", "homepage": "https://garak.ai", "repo_url": "https://github.com/NVIDIA/garak", "tagline": "LLM vulnerability scanner."},
    {"slug": "promptfoo", "name": "promptfoo", "vendor_handle": "promptfoo", "vendor_type": "org", "source_type": "open-source", "category": "security-pentesting", "homepage": "https://promptfoo.dev", "repo_url": "https://github.com/promptfoo/promptfoo", "tagline": "LLM eval and red-team framework."},
    # ----- science / education / reasoning (6)
    {"slug": "alphafold-server", "name": "AlphaFold Server", "vendor_handle": "Google DeepMind", "vendor_type": "company", "source_type": "closed-source", "category": "bioinformatics", "homepage": "https://alphafoldserver.com", "repo_url": None, "tagline": "Protein structure prediction service."},
    {"slug": "elicit", "name": "Elicit", "vendor_handle": "Elicit", "vendor_type": "company", "source_type": "closed-source", "category": "scientific-research", "homepage": "https://elicit.com", "repo_url": None, "tagline": "Research assistant for systematic review."},
    {"slug": "scispace", "name": "SciSpace", "vendor_handle": "SciSpace", "vendor_type": "company", "source_type": "closed-source", "category": "scientific-research", "homepage": "https://typeset.io", "repo_url": None, "tagline": "Read, summarize and cite papers with AI."},
    {"slug": "khanmigo", "name": "Khanmigo", "vendor_handle": "Khan Academy", "vendor_type": "company", "source_type": "closed-source", "category": "education-tutoring", "homepage": "https://khanmigo.ai", "repo_url": None, "tagline": "1-on-1 tutoring assistant for K-12."},
    {"slug": "magic-school", "name": "MagicSchool", "vendor_handle": "MagicSchool", "vendor_type": "company", "source_type": "closed-source", "category": "education-tutoring", "homepage": "https://magicschool.ai", "repo_url": None, "tagline": "AI toolkit for teachers."},
    {"slug": "wolfram-llm", "name": "Wolfram LLM Tool", "vendor_handle": "Wolfram", "vendor_type": "company", "source_type": "closed-source", "category": "reasoning-math", "homepage": "https://wolfram.com", "repo_url": None, "tagline": "Symbolic math + computational knowledge for LLMs."},
    # ----- multi-agent orchestration (4)
    {"slug": "smolagents", "name": "smolagents", "vendor_handle": "Hugging Face", "vendor_type": "company", "source_type": "open-source", "category": "multi-agent-orchestration", "homepage": "https://huggingface.co/docs/smolagents", "repo_url": "https://github.com/huggingface/smolagents", "tagline": "Minimal code-first agent framework."},
    {"slug": "openai-swarm", "name": "OpenAI Swarm", "vendor_handle": "OpenAI", "vendor_type": "company", "source_type": "open-source", "category": "multi-agent-orchestration", "homepage": "https://github.com/openai/swarm", "repo_url": "https://github.com/openai/swarm", "tagline": "Lightweight handoff-based multi-agent runtime."},
    {"slug": "llama-agents", "name": "llama-agents", "vendor_handle": "LlamaIndex", "vendor_type": "company", "source_type": "open-source", "category": "multi-agent-orchestration", "homepage": "https://llamaindex.ai", "repo_url": "https://github.com/run-llama/llama-agents", "tagline": "Production-ready multi-agent system runtime."},
    {"slug": "microsoft-magentic", "name": "Magentic-One", "vendor_handle": "Microsoft Research", "vendor_type": "company", "source_type": "open-source", "category": "multi-agent-orchestration", "homepage": "https://www.microsoft.com/en-us/research/", "repo_url": "https://github.com/microsoft/autogen", "tagline": "AutoGen-based generalist multi-agent system."},
    # ----- healthcare / vertical (5)
    {"slug": "nuance-dax", "name": "Nuance DAX Copilot", "vendor_handle": "Microsoft (Nuance)", "vendor_type": "company", "source_type": "closed-source", "category": "healthcare", "homepage": "https://www.nuance.com/healthcare.html", "repo_url": None, "tagline": "Ambient clinical documentation."},
    {"slug": "abridge", "name": "Abridge", "vendor_handle": "Abridge", "vendor_type": "company", "source_type": "closed-source", "category": "healthcare", "homepage": "https://abridge.com", "repo_url": None, "tagline": "Clinical conversation summarization."},
    {"slug": "clay-agent", "name": "Clay", "vendor_handle": "Clay", "vendor_type": "company", "source_type": "closed-source", "category": "sales-crm", "homepage": "https://clay.com", "repo_url": None, "tagline": "GTM data + agentic outbound enrichment."},
    {"slug": "anyword", "name": "Anyword", "vendor_handle": "Anyword", "vendor_type": "company", "source_type": "closed-source", "category": "marketing", "homepage": "https://anyword.com", "repo_url": None, "tagline": "Predictive marketing copywriter."},
    {"slug": "house-canary-ai", "name": "HouseCanary AI", "vendor_handle": "HouseCanary", "vendor_type": "company", "source_type": "closed-source", "category": "real-estate", "homepage": "https://housecanary.com", "repo_url": None, "tagline": "Property valuation AI for real-estate ops."},
    # ----- knowledge / spreadsheet / sql / misc (4)
    {"slug": "mem-ai", "name": "Mem", "vendor_handle": "Mem Labs", "vendor_type": "company", "source_type": "closed-source", "category": "knowledge-management", "homepage": "https://mem.ai", "repo_url": None, "tagline": "Self-organizing personal knowledge base."},
    {"slug": "rows-ai", "name": "Rows AI", "vendor_handle": "Rows", "vendor_type": "company", "source_type": "closed-source", "category": "spreadsheet-excel", "homepage": "https://rows.com", "repo_url": None, "tagline": "Natural-language spreadsheet operations."},
    {"slug": "textql", "name": "TextQL", "vendor_handle": "TextQL", "vendor_type": "company", "source_type": "closed-source", "category": "sql-analytics", "homepage": "https://textql.com", "repo_url": None, "tagline": "Enterprise data agent over BI sources."},
    {"slug": "vanna-ai", "name": "Vanna AI", "vendor_handle": "Vanna", "vendor_type": "company", "source_type": "open-source", "category": "sql-analytics", "homepage": "https://vanna.ai", "repo_url": "https://github.com/vanna-ai/vanna", "tagline": "RAG-driven NL-to-SQL agent."},
]

assert len({s["slug"] for s in SEEDS}) == len(SEEDS), "duplicate slugs in SEEDS"
assert len(SEEDS) == 70, f"expected 70 SEEDS, got {len(SEEDS)}"


CategoryPreset = TypedDict("CategoryPreset", {
    "capabilities": dict,
    "io_surfaces": dict,
    "data_classes_touched": list[str],
    "sandboxing": dict,
    "concurrency_model": dict,
})


def _coding_preset() -> CategoryPreset:
    return {
        "capabilities": {
            "execute_shell": True, "read_filesystem": True, "write_filesystem": True,
            "network_egress": "broad", "spawn_subprocesses": True, "use_mcp": False,
            "modify_git_state": True, "install_packages": True, "run_browsers": False,
        },
        "io_surfaces": {"stdin_stdout": True, "files": ["repo files"], "clipboard": False, "screen_capture": False, "audio": False, "calls_apis": ["model vendor inference"]},
        "data_classes_touched": ["source code", "git history"],
        "sandboxing": {"self_isolation": "none — host process", "subagent_model": "single agent", "tool_use_pattern": "tool-call loop"},
        "concurrency_model": {"session_scope": "per-IDE-window", "shared_state_with_other_instances": "via filesystem", "supports_multiple_instances": True},
    }


def _web_preset() -> CategoryPreset:
    p = _coding_preset(); p["data_classes_touched"] = ["source code", "design tokens"]; return p


def _browser_preset() -> CategoryPreset:
    return {
        "capabilities": {
            "execute_shell": False, "read_filesystem": False, "write_filesystem": False,
            "network_egress": "broad", "spawn_subprocesses": False, "use_mcp": False,
            "modify_git_state": False, "install_packages": False, "run_browsers": True,
        },
        "io_surfaces": {"stdin_stdout": True, "files": [], "clipboard": True, "screen_capture": True, "audio": False, "calls_apis": ["model vendor inference", "user-visited sites"]},
        "data_classes_touched": ["browsing history", "page DOM", "user credentials in browser"],
        "sandboxing": {"self_isolation": "browser sandbox", "subagent_model": "single agent", "tool_use_pattern": "browser tool-call loop"},
        "concurrency_model": {"session_scope": "per-browser-tab", "shared_state_with_other_instances": "via cookies/localStorage", "supports_multiple_instances": True},
    }


def _os_preset() -> CategoryPreset:
    return {
        "capabilities": {
            "execute_shell": True, "read_filesystem": True, "write_filesystem": True,
            "network_egress": "broad", "spawn_subprocesses": True, "use_mcp": False,
            "modify_git_state": False, "install_packages": True, "run_browsers": True,
        },
        "io_surfaces": {"stdin_stdout": True, "files": ["host filesystem"], "clipboard": True, "screen_capture": True, "audio": False, "calls_apis": ["model vendor inference"]},
        "data_classes_touched": ["screen contents", "host filesystem", "keystrokes"],
        "sandboxing": {"self_isolation": "VM/container recommended", "subagent_model": "single agent", "tool_use_pattern": "screenshot+action loop"},
        "concurrency_model": {"session_scope": "per-virtual-display", "shared_state_with_other_instances": "via filesystem", "supports_multiple_instances": False},
    }


def _saas_preset() -> CategoryPreset:
    return {
        "capabilities": {
            "execute_shell": False, "read_filesystem": False, "write_filesystem": False,
            "network_egress": "vendor-only", "spawn_subprocesses": False, "use_mcp": False,
            "modify_git_state": False, "install_packages": False, "run_browsers": False,
        },
        "io_surfaces": {"stdin_stdout": True, "files": [], "clipboard": False, "screen_capture": False, "audio": False, "calls_apis": ["vendor backend"]},
        "data_classes_touched": ["uploaded user data"],
        "sandboxing": {"self_isolation": "vendor-managed multi-tenant", "subagent_model": "single agent", "tool_use_pattern": "vendor tool-call loop"},
        "concurrency_model": {"session_scope": "per-account-session", "shared_state_with_other_instances": "via vendor backend", "supports_multiple_instances": True},
    }


def _media_preset() -> CategoryPreset:
    p = _saas_preset(); p["data_classes_touched"] = ["uploaded media", "prompt content"]; return p


def _orchestration_preset() -> CategoryPreset:
    return {
        "capabilities": {
            "execute_shell": False, "read_filesystem": True, "write_filesystem": True,
            "network_egress": "broad", "spawn_subprocesses": True, "use_mcp": True,
            "modify_git_state": False, "install_packages": False, "run_browsers": False,
        },
        "io_surfaces": {"stdin_stdout": True, "files": ["agent state"], "clipboard": False, "screen_capture": False, "audio": False, "calls_apis": ["multiple model vendors"]},
        "data_classes_touched": ["inter-agent messages"],
        "sandboxing": {"self_isolation": "framework-level", "subagent_model": "graph of agents", "tool_use_pattern": "router + workers"},
        "concurrency_model": {"session_scope": "per-runtime", "shared_state_with_other_instances": "via shared memory", "supports_multiple_instances": True},
    }


CATEGORY_PRESETS: dict[str, CategoryPreset] = {
    "coding": _coding_preset(),
    "web-dev": _web_preset(),
    "data-engineering": _coding_preset(),
    "data-science-ml": _coding_preset(),
    "financial-modeling": _saas_preset(),
    "legal-research": _saas_preset(),
    "customer-support": _saas_preset(),
    "content-writing": _saas_preset(),
    "image-generation": _media_preset(),
    "video-generation": _media_preset(),
    "audio-speech": _media_preset(),
    "translation": _saas_preset(),
    "search-rag": _saas_preset(),
    "browser-automation": _browser_preset(),
    "desktop-os-automation": _os_preset(),
    "document-processing": _saas_preset(),
    "email-scheduling": _saas_preset(),
    "devops-sre": _coding_preset(),
    "security-pentesting": _coding_preset(),
    "bioinformatics": _saas_preset(),
    "scientific-research": _saas_preset(),
    "education-tutoring": _saas_preset(),
    "reasoning-math": _saas_preset(),
    "multi-agent-orchestration": _orchestration_preset(),
    "healthcare": _saas_preset(),
    "sales-crm": _saas_preset(),
    "marketing": _saas_preset(),
    "real-estate": _saas_preset(),
    "knowledge-management": _saas_preset(),
    "spreadsheet-excel": _saas_preset(),
    "sql-analytics": _saas_preset(),
}


__all__ = ["SEEDS", "CATEGORY_PRESETS", "Seed", "CategoryPreset"]
