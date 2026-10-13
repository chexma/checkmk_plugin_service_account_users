#!/usr/bin/env python3
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
