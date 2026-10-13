#!/usr/bin/env python3
# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Bakery plugin: deploys service_accounts.ps1 to Windows hosts."""

from pathlib import Path
from typing import Literal

from cmk.bakery.v2_unstable import OS, BakeryPlugin, FileGenerator, Plugin
from pydantic import BaseModel


class Config(BaseModel):
    deployment: tuple[Literal["deploy", "do_not_deploy"], None]
    interval: float | None = None


def get_service_accounts_files(conf: Config) -> FileGenerator:
    if conf.deployment[0] != "deploy":
        return
    yield Plugin(
        base_os=OS.WINDOWS,
        source=Path("service_accounts.ps1"),
        interval=conf.interval,
    )


bakery_plugin_service_accounts = BakeryPlugin(
    name="service_accounts",
    parameter_parser=Config.model_validate,
    default_parameters=None,
    files_function=get_service_accounts_files,
)
