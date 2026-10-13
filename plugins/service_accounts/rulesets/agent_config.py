#!/usr/bin/env python3
# Copyright (C) 2026 chexma - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Bakery rule for the agent plugin service_accounts.ps1."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    CascadingSingleChoice,
    CascadingSingleChoiceElement,
    DefaultValue,
    DictElement,
    Dictionary,
    FixedValue,
    TimeMagnitude,
    TimeSpan,
)
from cmk.rulesets.v1.rule_specs import AgentConfig, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        help_text=Help(
            "Deploys the agent plugin <tt>service_accounts.ps1</tt>, which reports every "
            "Windows service and the account it runs under. What counts as a service "
            "account and which accounts are allowed is set in the rule <i>Service accounts "
            "(Windows)</i> for the service, so changing that never requires baking agents."
        ),
        elements={
            "deployment": DictElement(
                required=True,
                parameter_form=CascadingSingleChoice(
                    title=Title("Deployment"),
                    prefill=DefaultValue("deploy"),
                    elements=[
                        CascadingSingleChoiceElement(
                            name="deploy",
                            title=Title("Deploy the plugin"),
                            parameter_form=FixedValue(value=None),
                        ),
                        CascadingSingleChoiceElement(
                            name="do_not_deploy",
                            title=Title("Do not deploy the plugin"),
                            parameter_form=FixedValue(value=None),
                        ),
                    ],
                ),
            ),
            "interval": DictElement(
                parameter_form=TimeSpan(
                    title=Title("Run asynchronously and cache the result"),
                    help_text=Help(
                        "Translating accounts of a domain that is not reachable can take a "
                        "while. With this option the plugin runs in the background and the "
                        "agent delivers the cached result."
                    ),
                    label=Label("Interval"),
                    displayed_magnitudes=[TimeMagnitude.HOUR, TimeMagnitude.MINUTE],
                    prefill=DefaultValue(3600.0),
                ),
            ),
        },
    )


rule_spec_service_accounts_bakery = AgentConfig(
    name="service_accounts",
    title=Title("Service accounts (Windows)"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
)
