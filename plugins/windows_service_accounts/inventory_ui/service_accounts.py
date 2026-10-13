#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Titles and view of the inventory table software > os > service_accounts."""

from cmk.inventory_ui.v1_unstable import ChoiceField, Node, Table, TextField, Title, View

node_software_os_service_accounts = Node(
    name="software_os_service_accounts",
    path=["software", "os", "service_accounts"],
    title=Title("Windows Service Accounts"),
    table=Table(
        view=View(name="invserviceaccounts", title=Title("Windows Service Accounts")),
        columns={
            "service": TextField(Title("Service")),
            "display_name": TextField(Title("Display name")),
            "account": TextField(Title("Account")),
            "kind": ChoiceField(
                Title("Kind"),
                mapping={
                    "local_system": "Local System",
                    "local_service": "Local Service",
                    "network_service": "Network Service",
                    "virtual": "Virtual account",
                    "no_account": "No account",
                    "local_user": "Local user",
                    "managed": "Managed service account",
                    "domain": "Domain account",
                    "unknown": "Unknown",
                },
            ),
            "start_mode": TextField(Title("Start mode")),
            "state": TextField(Title("State")),
        },
    ),
)
