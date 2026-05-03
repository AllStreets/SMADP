# Aider adapter

[Aider](https://aider.chat) is an open-source AI pair-programmer that runs as a
terminal application and edits files inside a local git repository. SMADP runs
Aider inside the Sandbox Validator with `--no-auto-commits --no-git --yes` so
that file edits produce observable transcript events without coupling the
sandbox to git state. The adapter requires `OPENAI_API_KEY` (or
`ANTHROPIC_API_KEY` for Claude models); the Sandbox Validator injects only a
synthetic stand-in value because outbound network egress is denied unless a
scenario explicitly allow-lists `api.openai.com`/`api.anthropic.com`. The
container runs as `nobody`, with `--cap-drop ALL` and a tmpfs-only working
directory, and is destroyed at scenario end.
