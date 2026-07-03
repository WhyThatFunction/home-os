"""Errors — Aggregated dashboard.

A single-purpose, errors-ONLY board that answers "what is broken, how often, and
when did it last happen?" at a glance, aggregated across the whole estate:

  * an aggregated TABLE — one row per (service_name, service_version) with the
    error COUNT over the dashboard range and the LAST OCCURRENCE timestamp;
  * an error-rate TIMESERIES by service_name (same query style as global-errors);
  * a STAT row — total errors in range + distinct services with errors.

`service_version` is expected to be a Loki structured-metadata/label carried from
the OTel resource attribute `service.version` (normalized to `service_version`).
Queries are written DEFENSIVELY: if the label is absent the group-by simply
collapses to per-service rows (an empty version cell) — no query error — and the
board self-heals once clients start reporting a version. A `$service`
multi-select narrows every panel.
"""

from __future__ import annotations

from grafana_foundation_sdk.builders import dashboard as dash
from grafana_foundation_sdk.models.dashboard import (
    GridPos,
    VariableRefresh,
    VariableSort,
)

import lib

UID = "errors-aggregated"
CR_NAME = "errors-aggregated"

# `$service` multi-select over Loki's service_name label values; "All" -> `.*`.
SERVICE_MATCHER = 'service_name =~ "$service"'
ERROR_SEVERITY = "severity_text =~ `ERROR|FATAL`"


def _service_variable() -> dash.QueryVariable:
    return (
        dash.QueryVariable("service")
        .label("Service")
        .datasource(lib.LOKI)
        .query({"label": "service_name", "stream": "", "type": 1})
        .refresh(VariableRefresh.ON_TIME_RANGE_CHANGED)
        .sort(VariableSort.ALPHABETICAL_ASC)
        .multi(True)
        .include_all(True)
        .all_value(".*")
    )


def build() -> dash.Dashboard:
    # ── Stat row ────────────────────────────────────────────────────────────
    total_errors = lib.stat_view(
        "Total errors (range)",
        lib.LOKI,
        lib.loki_query(
            f"sum(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__range]))"
        ),
        unit="short",
        calc="lastNotNull",
    ).grid_pos(GridPos(h=5, w=6, x=0, y=0))

    distinct_services = lib.stat_view(
        "Services with errors",
        lib.LOKI,
        lib.loki_query(
            f"count(sum by (service_name) "
            f"(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__range])))"
        ),
        unit="short",
        calc="lastNotNull",
    ).grid_pos(GridPos(h=5, w=6, x=6, y=0))

    error_rate_by_service = lib.timeseries_panel(
        "Error rate by service",
        lib.LOKI,
        lib.loki_query(
            f"sum by (service_name) "
            f"(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__auto]))"
        ),
    ).grid_pos(GridPos(h=5, w=12, x=12, y=0))

    # ── Aggregated table: count + last occurrence per (service, version) ──────
    # Two Loki targets feed ONE table:
    #   A) an INSTANT metric query → one series (= one row) per (service_name,
    #      service_version) with the error COUNT as its single value;
    #   B) a raw logs query whose per-line Time we reduce to a max (last
    #      occurrence) grouped by the same labels.
    # Grafana transformations then join/group both into a tidy table. We keep the
    # group-by on the metric target's label fields; service_version participates
    # only if the label exists (defensive — see module docstring).
    count_target = lib.loki_instant_query(
        f"sum by (service_name, service_version) "
        f"(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__range]))",
        ref_id="A",
    )
    last_seen_target = lib.loki_query(
        f"{{{SERVICE_MATCHER}}} | {ERROR_SEVERITY}",
        ref_id="B",
    )

    aggregated_table = (
        lib.table_view(
            "Errors by service & version — count + last seen",
            lib.LOKI,
            count_target,
            last_seen_target,
        )
        # 1) Collapse the raw B logs to last-occurrence per (service, version).
        #    Scoped to frame B so the A count series passes through untouched.
        .with_transformation(
            lib.group_by(
                {
                    "service_name": {"aggregations": [], "operation": "groupby"},
                    "service_version": {"aggregations": [], "operation": "groupby"},
                    "Time": {"aggregations": ["lastNotNull"], "operation": "aggregate"},
                },
                ref_id="B",
            )
        )
        # 2) Merge the count series (A) and the last-seen frame (B) into one table
        #    keyed by the shared label columns.
        .with_transformation(lib.transformation("merge", {}))
        # 3) Tidy up: rename to human headers and fix column order.
        .with_transformation(
            lib.organize(
                rename={
                    "service_name": "Service",
                    "service_version": "Version",
                    "Value #A": "Error count",
                    "Value": "Error count",
                    "Time (lastNotNull)": "Last occurrence",
                    "Time": "Last occurrence",
                },
                order=[
                    "Service",
                    "Version",
                    "Error count",
                    "Last occurrence",
                ],
            )
        )
        .grid_pos(GridPos(h=12, w=24, x=0, y=5))
    )

    return (
        dash.Dashboard("Errors — Aggregated")
        .uid(UID)
        .refresh("1m")
        .time("now-24h", "now")
        .tags(["errors", "aggregated", "sre"])
        .with_variable(_service_variable())
        .with_panel(total_errors)
        .with_panel(distinct_services)
        .with_panel(error_rate_by_service)
        .with_panel(aggregated_table)
    )
