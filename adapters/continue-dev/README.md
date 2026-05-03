# Continue adapter

[Continue](https://continue.dev) is an open-source AI code assistant primarily
distributed as a VS Code / JetBrains extension; SMADP drives only its headless
Node core (`@continuedev/core`) so the IDE-coupled surfaces (clipboard, screen
capture, editor selections) are out of play in sandbox runs. The container is
launched with the task injected through the `SMADP_AGENT_TASK` env var, runs as
`nobody` with `--cap-drop ALL`, and uses a tmpfs working directory at `/work`.
Network egress is denied by default; scenarios that require Continue's hosted
inference must explicitly allow-list `api.continue.dev` (and any chosen model
provider) and route traffic through the recording proxy.
