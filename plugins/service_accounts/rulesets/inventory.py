#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Parameters of the inventory table software > os > service_accounts."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import BooleanChoice, DefaultValue, DictElement, Dictionary
from cmk.rulesets.v1.rule_specs import InventoryParameters, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "all_services": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Services in the inventory table"),
                    label=Label("Also list services under built-in accounts"),
                    help_text=Help(
                        "By default the table <i>Software > Operating system > Windows Service "
                        "Accounts</i> only contains services that run under a service "
                        "account, so a host without service accounts has no table. With "
                        "this option it contains every Windows service of the host, also "
                        "the ones running as Local System, Local Service, Network Service, "
                        "under a virtual account or without an account. The column "
                        "<i>Kind</i> tells them apart."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
        },
    )


rule_spec_service_accounts_inventory = InventoryParameters(
    name="service_accounts_inventory",
    title=Title("Service accounts (Windows)"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
)
