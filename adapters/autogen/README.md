# AutoGen adapter

[AutoGen](https://github.com/microsoft/autogen) is a Microsoft Research
multi-agent framework whose `UserProxyAgent` executes LLM-emitted code by
default — exactly the kind of capability that motivates SMADP's outer
sandbox. The adapter runs AutoGen with `--no-human-input` so it never blocks
on a TTY, and sets `AUTOGEN_USE_DOCKER=0` because spawning a docker daemon
inside an already-sandboxed container would either fail or escalate
isolation costs without benefit. The container relies on the standard
`--cap-drop ALL`, `no-new-privileges`, gVisor (when available) envelope to
contain shell-outs that AutoGen produces. Outbound network is denied unless a
scenario allow-lists `api.openai.com` (or an Azure OpenAI endpoint) through
the recording proxy.
