"""Shared helpers for the otel-lgtm dashboards-as-code generator.

House rule (repo owner): never hand-write a Grafana dashboard JSON again — always
generate it from Python. This module holds the reusable bits so each dashboard
module (dashboards/*.py) stays a thin, declarative description:

  * datasource refs for the uids the grafana/otel-lgtm image provisions
    (prometheus / loki / tempo / pyroscope);
  * small panel + query factories built on the official grafana-foundation-sdk;
  * the CR-wrapping function that turns a built dashboard dict into a
    `GrafanaDashboard` CR YAML string the Grafana Operator reconciles.

Everything here is typed via the SDK; we do not assemble raw panel JSON by hand.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from grafana_foundation_sdk.builders import (
    dashboard as dash,
    logs as logs_panel,
    stat as stat_panel,
    table as table_panel,
    timeseries as ts_panel,
)
from grafana_foundation_sdk.builders.loki import Dataquery as LokiQuery
from grafana_foundation_sdk.builders.tempo import TempoQuery
from grafana_foundation_sdk.cog.encoder import JSONEncoder
from grafana_foundation_sdk.models.dashboard import DataSourceRef

# --------------------------------------------------------------------------- #
# Datasource refs — the uids grafana/otel-lgtm provisions out of the box.
# Verified against docker-otel-lgtm's grafana-datasources.yaml.
# --------------------------------------------------------------------------- #
PROMETHEUS = DataSourceRef(type_val="prometheus", uid="prometheus")
LOKI = DataSourceRef(type_val="loki", uid="loki")
TEMPO = DataSourceRef(type_val="tempo", uid="tempo")
PYROSCOPE = DataSourceRef(type_val="grafana-pyroscope-datasource", uid="pyroscope")

# CR metadata shared by every generated GrafanaDashboard. `dashboards: otel-lgtm`
# is the instanceSelector the operator uses to bind to the external Grafana (see
# templates/grafana-instance.yaml). app/team match the chart's label convention.
INSTANCE_SELECTOR = {"dashboards": "otel-lgtm"}
CR_LABELS = {"app": "otel-lgtm", "team": "ssegning-home"}

GENERATED_HEADER = (
    "# GENERATED — do not edit by hand.\n"
    "# Source: charts/home-apps/otel-lgtm/dashboards/dashboards/{module}.py\n"
    "# Edit the .py and re-run `python generate.py` (or `make dashboards`).\n"
)


# --------------------------------------------------------------------------- #
# Query factories
# --------------------------------------------------------------------------- #
def loki_query(expr: str, ref_id: str = "A") -> LokiQuery:
    """A Loki target. `expr` is LogQL."""
    return LokiQuery().expr(expr).ref_id(ref_id)


def tempo_traceql(query: str, ref_id: str = "A", limit: int = 50) -> TempoQuery:
    """A Tempo target using TraceQL (query_type='traceql')."""
    return TempoQuery().query_type("traceql").query(query).ref_id(ref_id).limit(limit)


# --------------------------------------------------------------------------- #
# Panel factories — each returns an SDK panel builder; callers place them with
# `.grid_pos(...)` via the helpers below or the dashboard auto-layout.
# --------------------------------------------------------------------------- #
def timeseries_panel(title: str, datasource: DataSourceRef, *targets) -> ts_panel.Panel:
    p = ts_panel.Panel().title(title).datasource(datasource)
    for t in targets:
        p = p.with_target(t)
    return p


def logs_view(
    title: str,
    datasource: DataSourceRef,
    *targets,
    sort_descending: bool = True,
) -> logs_panel.Panel:
    from grafana_foundation_sdk.models.common import LogsSortOrder

    p = (
        logs_panel.Panel()
        .title(title)
        .datasource(datasource)
        .show_time(True)
        .wrap_log_message(True)
        .enable_log_details(True)
        .sort_order(
            LogsSortOrder.DESCENDING if sort_descending else LogsSortOrder.ASCENDING
        )
    )
    for t in targets:
        p = p.with_target(t)
    return p


def table_view(title: str, datasource: DataSourceRef, *targets) -> table_panel.Panel:
    p = table_panel.Panel().title(title).datasource(datasource)
    for t in targets:
        p = p.with_target(t)
    return p


def stat_view(
    title: str,
    datasource: DataSourceRef,
    *targets,
    unit: str = "short",
    calc: str = "sum",
) -> stat_panel.Panel:
    from grafana_foundation_sdk.builders.common import ReduceDataOptions

    p = (
        stat_panel.Panel()
        .title(title)
        .datasource(datasource)
        .unit(unit)
        .reduce_options(ReduceDataOptions().calcs([calc]).values(False))
    )
    for t in targets:
        p = p.with_target(t)
    return p


# --------------------------------------------------------------------------- #
# Serialization + CR wrapping
# --------------------------------------------------------------------------- #
def dashboard_to_dict(builder: dash.Dashboard) -> dict[str, Any]:
    """Build the dashboard and return it as a plain dict (via the SDK encoder)."""
    model = builder.build()
    return json.loads(JSONEncoder(sort_keys=False, indent=None).encode(model))


def wrap_cr(
    *,
    cr_name: str,
    module: str,
    dashboard_json: dict[str, Any],
) -> str:
    """Wrap a built dashboard dict in a GrafanaDashboard CR and render to YAML.

    The operator reconciles the inline JSON over Grafana's HTTP API; the uid in
    the JSON keeps the dashboard URL stable across regenerations.
    """
    cr = {
        "apiVersion": "grafana.integreatly.org/v1beta1",
        "kind": "GrafanaDashboard",
        "metadata": {"name": cr_name, "labels": dict(CR_LABELS)},
        "spec": {
            "instanceSelector": {"matchLabels": dict(INSTANCE_SELECTOR)},
            # resyncPeriod keeps the dashboard converged if someone click-edits it.
            "resyncPeriod": "5m",
            "json": json.dumps(dashboard_json, indent=2, ensure_ascii=False),
        },
    }
    body = yaml.safe_dump(cr, sort_keys=False, default_flow_style=False, width=4096)
    return GENERATED_HEADER.format(module=module) + body
