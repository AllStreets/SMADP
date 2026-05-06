# Aider adapter

[Aider](https://aider.chat) is an open-source AI pair-programmer that runs as a
terminal application and edits files inside a local git repository. SMADP runs
Aider inside the Sandbox Validator with `--no-auto-commits --no-git --yes
--model gpt-5.4-mini` so that file edits produce observable transcript events
without coupling the sandbox to git state. The adapter requires
`OPENAI_API_KEY`; the Sandbox Validator injects only a synthetic stand-in value
because outbound network egress is denied unless a scenario explicitly
allow-lists `api.openai.com`. The container runs as `nobody`, with `--cap-drop
ALL` and a tmpfs-only working directory, and is destroyed at scenario end.
