.PHONY: sandbox-smoke

# Smoke set: aider is the only public-image adapter pinned to a real digest
# today (autogen/continue-dev/open-interpreter don't ship as containers). Each
# pairing uses synthetic-adapter as the second slot so the pipeline runs
# without us fabricating Dockerfiles for tools that don't have one.
sandbox-smoke:
	@echo "==> Enqueuing one run per scenario (aider x synthetic-adapter)"
	python -m smadp.cli sandbox run aider synthetic-adapter --scenario calendar_email
	python -m smadp.cli sandbox run aider synthetic-adapter --scenario notes_email
	python -m smadp.cli sandbox run aider synthetic-adapter --scenario spreadsheet_powerpoint
	@echo "==> Draining the queue"
	python -m smadp.cli sandbox work --max 3
	@echo "==> Done. Inspect catalog/verdicts/ for sandbox-validated entries."
