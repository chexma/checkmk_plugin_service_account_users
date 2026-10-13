#!/usr/bin/env python3
"""Windows services and the accounts they run under.

Section <<<service_accounts:sep(124)>>> (agent plugin service_accounts.ps1):

    computer|<computer name>|<machine SID>
    service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
    error|<message>
"""

from collections.abc import Sequence
from dataclasses import dataclass

from cmk.agent_based.v2 import AgentSection, StringTable


@dataclass(frozen=True)
class WinService:
    name: str
    display_name: str
    account: str
    sid: str
    start_mode: str
    state: str


@dataclass(frozen=True)
class Section:
    computer: str
    machine_sid: str
    services: Sequence[WinService]
    error: str | None


def parse_service_accounts(string_table: StringTable) -> Section | None:
    if not string_table:
        return None
    computer = machine_sid = ""
    services = []
    error = None
    for line in string_table:
        if not line:
            continue
        fields = [field.strip() for field in line]
        match fields[0]:
            case "computer":
                computer, machine_sid = (fields[1:] + ["", ""])[:2]
            case "service" if len(fields) > 1 and fields[1]:
                services.append(WinService(*(fields[1:] + [""] * 6)[:6]))
            case "error":
                error = " ".join(fields[1:]) or "unknown error"
    return Section(computer, machine_sid.upper(), services, error)


agent_section_service_accounts = AgentSection(
    name="service_accounts",
    parse_function=parse_service_accounts,
)
