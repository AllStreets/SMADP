.PHONY: sandbox-smoke

sandbox-smoke:
	@echo "==> Enqueuing one run per scenario for the four shipped adapters"
	python -m smadp.cli sandbox run aider continue-dev --scenario calendar_email
	python -m smadp.cli sandbox run aider open-interpreter --scenario notes_email
	python -m smadp.cli sandbox run autogen open-interpreter --scenario spreadsheet_powerpoint
	@echo "==> Draining the queue"
	python -m smadp.cli sandbox work --max 3
	@echo "==> Done. Inspect catalog/verdicts/ for sandbox-validated entries."
