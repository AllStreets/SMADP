# Open Interpreter adapter

[Open Interpreter](https://openinterpreter.com) is one of the most
capability-rich agents in the catalog: it converts natural-language requests
into Python / shell / AppleScript / JS and runs them on the host. SMADP runs
it inside the airtight container with `--auto_run` enabled (skipping its
interactive per-command confirmation prompt), which would be reckless on a
real workstation but is appropriate inside a `--cap-drop ALL`,
`no-new-privileges`, gVisor-when-available envelope. The container exposes no
audio device, no clipboard, no host home directory, and a tmpfs-only
`/work`. Because Open Interpreter has the broadest `network_egress` surface
in v1, scenarios requesting Internet must allow-list the specific inference
endpoint rather than using a permissive bridge.
