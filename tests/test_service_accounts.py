"""Tests for the plugin family service_accounts. All names are fictional."""

import pytest
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa

MACHINE_SID = "S-1-5-21-1000-2000-3000"
DOMAIN_SID = "S-1-5-21-4000-5000-6000"

# What the agent plugin prints, without the section header.
AGENT_OUTPUT = f"""\
computer|SRV-APP01|{MACHINE_SID}
service|Spooler|Print Spooler|LocalSystem|S-1-5-18|Auto|Running
service|Dhcp|DHCP Client|NT AUTHORITY\\LocalService|S-1-5-19|Auto|Running
service|Dnscache|DNS Client|NT-AUTORITÄT\\Netzwerkdienst|S-1-5-20|Auto|Running
service|MSSQL$X|SQL Server (X)|NT SERVICE\\MSSQL$X|S-1-5-80-1-2-3-4-5|Auto|Running
service|MSSQLSERVER|SQL Server|CONTOSO\\svc_sql|{DOMAIN_SID}-1105|Auto|Running
service|SQLAgent|SQL Server Agent|CONTOSO\\svc_sql|{DOMAIN_SID}-1105|Manual|Stopped
service|Backup|Backup Service|.\\backup|{MACHINE_SID}-1001|Disabled|Stopped
service|WebApp|Web App|CONTOSO\\gmsa_web$|{DOMAIN_SID}-1106|Auto|Running
service|Legacy|Legacy App|CONTOSO\\old_admin||Auto|Stopped
"""


def _table(text: str) -> list[list[str]]:
    """Agent output as the string table Checkmk passes to the parse function."""
    return [line.split("|") for line in text.splitlines()]


STRING_TABLE = _table(AGENT_OUTPUT)


@pytest.fixture(name="section")
def _section() -> sa.Section:
    section = sa.parse_service_accounts(STRING_TABLE)
    assert section is not None
    return section


# --- parser -----------------------------------------------------------------


def test_parse_empty_section() -> None:
    assert sa.parse_service_accounts([]) is None


def test_parse_services(section) -> None:
    assert section.computer == "SRV-APP01"
    assert section.machine_sid == MACHINE_SID
    assert section.error is None
    assert len(section.services) == 9
    assert section.services[4] == sa.WinService(
        name="MSSQLSERVER",
        display_name="SQL Server",
        account="CONTOSO\\svc_sql",
        sid=DOMAIN_SID + "-1105",
        start_mode="Auto",
        state="Running",
    )


def test_parse_empty_and_missing_fields() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01"],
            ["service", "NoAccount", "No Account", "", "", "Manual", "Stopped"],
            ["service", "Short", "Short Line"],
            ["service", ""],
            ["service"],
            ["garbage", "x"],
        ]
    )
    assert section is not None
    assert section.machine_sid == ""
    assert [s.name for s in section.services] == ["NoAccount", "Short"]
    assert section.services[0].account == ""
    assert section.services[1] == sa.WinService("Short", "Short Line", "", "", "", "")


def test_parse_error_line() -> None:
    section = sa.parse_service_accounts(
        [["computer", "SRV-APP01", MACHINE_SID], ["error", "Access denied"]]
    )
    assert section is not None
    assert section.error == "Access denied"
    assert section.services == []


def test_parse_german_account_name(section) -> None:
    assert section.services[2].account == "NT-AUTORITÄT\\Netzwerkdienst"
