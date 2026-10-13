#!/usr/bin/env python3
"""Metrics, graph and perfometer of the service "Service Accounts"."""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, StrictPrecision, Unit
from cmk.graphing.v1.perfometers import Closed, FocusRange, Open, Perfometer

_UNIT_COUNT = Unit(DecimalNotation(""), StrictPrecision(0))

metric_service_account_services = Metric(
    name="service_account_services",
    title=Title("Services under service accounts"),
    unit=_UNIT_COUNT,
    color=Color.BLUE,
)

metric_service_account_accounts = Metric(
    name="service_account_accounts",
    title=Title("Service accounts"),
    unit=_UNIT_COUNT,
    color=Color.ORANGE,
)

graph_service_accounts = Graph(
    name="service_accounts",
    title=Title("Service accounts"),
    simple_lines=["service_account_services", "service_account_accounts"],
    minimal_range=MinimalRange(0, 10),
)

perfometer_service_accounts = Perfometer(
    name="service_accounts",
    focus_range=FocusRange(Closed(0), Open(20)),
    segments=["service_account_services"],
)
