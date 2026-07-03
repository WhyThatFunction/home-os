# home-os convenience targets.

DASHBOARDS_DIR := charts/home-apps/otel-lgtm/dashboards
VENV := $(DASHBOARDS_DIR)/.venv

.PHONY: dashboards dashboards-clean

## dashboards: regenerate the otel-lgtm Grafana dashboard CRs from Python.
## Never hand-edit templates/generated/*.yaml — edit the .py and run this.
dashboards:
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(VENV)/bin/pip install -q -r $(DASHBOARDS_DIR)/requirements.txt
	@cd $(DASHBOARDS_DIR) && .venv/bin/python generate.py

## dashboards-clean: drop the local generator venv.
dashboards-clean:
	rm -rf $(VENV)
