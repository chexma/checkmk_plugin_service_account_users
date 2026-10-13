"""Tests for the plugin family service_accounts. All names are fictional."""

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State
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


def _results(params, section) -> list[Result]:
    return [r for r in sa.check_service_accounts(params, section) if isinstance(r, Result)]


def _discovered(section) -> dict:
    (service,) = sa.discover_service_accounts(section)
    return dict(service.parameters)


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


# --- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "account, sid, kind",
    [
        ("LocalSystem", "S-1-5-18", "local_system"),
        ("NT-AUTORITÄT\\Lokaler Dienst", "S-1-5-19", "local_service"),
        ("NT-AUTORITÄT\\Netzwerkdienst", "S-1-5-20", "network_service"),
        ("NT SERVICE\\MSSQL$X", "S-1-5-80-1-2-3-4-5", "virtual"),
        (".\\backup", MACHINE_SID + "-1001", "local_user"),
        ("SRV-APP01\\backup", MACHINE_SID + "-1001", "local_user"),
        ("CONTOSO\\gmsa_web$", DOMAIN_SID + "-1106", "managed"),
        ("CONTOSO\\svc_sql", DOMAIN_SID + "-1105", "domain"),
        ("svc_sql@contoso.example", DOMAIN_SID + "-1105", "domain"),
        ("CONTOSO\\svc_sql", DOMAIN_SID.lower() + "-1105", "domain"),
        ("IIS APPPOOL\\DefaultAppPool", "S-1-5-82-1-2-3-4-5", "unknown"),
    ],
)
def test_classify_by_sid(account: str, sid: str, kind: str) -> None:
    assert sa.classify(account, sid, "SRV-APP01", MACHINE_SID) == kind


@pytest.mark.parametrize(
    "account, kind",
    [
        ("LocalSystem", "local_system"),
        (".\\LocalSystem", "local_system"),
        ("nt authority\\system", "local_system"),
        ("NT AUTHORITY\\LocalService", "local_service"),
        ("NT AUTHORITY\\NetworkService", "network_service"),
        ("NT Service\\MSSQL$X", "virtual"),
        (".\\backup", "local_user"),
        ("srv-app01\\backup", "local_user"),
        ("CONTOSO\\gmsa_web$", "managed"),
        ("CONTOSO\\svc_sql", "domain"),
        ("svc_sql@contoso.example", "domain"),
        ("something", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_by_name(account: str, kind: str) -> None:
    assert sa.classify(account, "", "SRV-APP01", MACHINE_SID) == kind


def test_classify_without_machine_sid_uses_the_name_for_local_users() -> None:
    assert sa.classify(".\\backup", MACHINE_SID + "-1001", "SRV-APP01", "") == "local_user"
    assert sa.classify("CONTOSO\\svc_sql", DOMAIN_SID + "-1105", "SRV-APP01", "") == "domain"


def test_classify_machine_sid_is_not_a_string_prefix() -> None:
    # S-1-5-21-1000-2000-30001-500 belongs to another machine or domain
    assert sa.classify("CONTOSO\\x", MACHINE_SID + "1-500", "SRV-APP01", MACHINE_SID) == "domain"


# --- discovery --------------------------------------------------------------


def test_discovery_stores_all_services_not_running_as_local_system(section) -> None:
    assert _discovered(section) == {
        "discovered_services": {
            "Dhcp": {"account": "NT AUTHORITY\\LocalService", "sid": "S-1-5-19"},
            "Dnscache": {"account": "NT-AUTORITÄT\\Netzwerkdienst", "sid": "S-1-5-20"},
            "MSSQL$X": {"account": "NT SERVICE\\MSSQL$X", "sid": "S-1-5-80-1-2-3-4-5"},
            "MSSQLSERVER": {"account": "CONTOSO\\svc_sql", "sid": DOMAIN_SID + "-1105"},
            "SQLAgent": {"account": "CONTOSO\\svc_sql", "sid": DOMAIN_SID + "-1105"},
            "Backup": {"account": ".\\backup", "sid": MACHINE_SID + "-1001"},
            "WebApp": {"account": "CONTOSO\\gmsa_web$", "sid": DOMAIN_SID + "-1106"},
            "Legacy": {"account": "CONTOSO\\old_admin", "sid": ""},
        }
    }


def test_discovery_on_error_has_no_baseline() -> None:
    section = sa.parse_service_accounts([["computer", "SRV-APP01", ""], ["error", "boom"]])
    assert list(sa.discover_service_accounts(section)) == [Service()]


def test_no_discovery_without_services_and_error() -> None:
    section = sa.parse_service_accounts([["computer", "SRV-APP01", MACHINE_SID]])
    assert not list(sa.discover_service_accounts(section))


# --- check: summary, metrics, details ---------------------------------------


def test_check_without_rule_is_ok_and_counts(section) -> None:
    results = list(sa.check_service_accounts({}, section))
    assert results[0] == Result(state=State.OK, summary="5 services under 4 service accounts")
    assert Metric("service_account_services", 5) in results
    assert Metric("service_account_accounts", 4) in results
    assert all(r.state is State.OK for r in results if isinstance(r, Result))


def test_check_details_list_services_per_account(section) -> None:
    details = [r.details for r in _results({}, section)]
    assert (
        f"CONTOSO\\svc_sql (domain account, {DOMAIN_SID}-1105)\n"
        "  MSSQLSERVER (SQL Server): Auto, Running\n"
        "  SQLAgent (SQL Server Agent): Manual, Stopped"
    ) in details
    assert "CONTOSO\\old_admin (domain account)\n  Legacy (Legacy App): Auto, Stopped" in details


def test_check_singular() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01", MACHINE_SID],
            ["service", "A", "A", "CONTOSO\\svc_a", DOMAIN_SID + "-1", "Auto", "Running"],
        ]
    )
    assert _results({}, section)[0].summary == "1 service under 1 service account"


def test_check_same_account_with_and_without_sid_is_counted_by_key() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01", MACHINE_SID],
            ["service", "A", "A", "CONTOSO\\svc_a", DOMAIN_SID + "-1", "Auto", "Running"],
            ["service", "B", "B", "contoso\\SVC_A", DOMAIN_SID + "-1", "Auto", "Running"],
        ]
    )
    assert _results({}, section)[0].summary == "2 services under 1 service account"


def test_builtin_kinds(section) -> None:
    params = {"builtin_kinds": ["local_system", "domain", "managed", "local_user"]}
    assert _results(params, section)[0].summary == "3 services under 3 service accounts"


def test_ignore_disabled(section) -> None:
    assert (
        _results({"ignore_disabled": True}, section)[0].summary
        == "4 services under 3 service accounts"
    )


def test_query_error_state() -> None:
    section = sa.parse_service_accounts([["computer", "SRV-APP01", ""], ["error", "boom"]])
    assert list(sa.check_service_accounts({}, section)) == [
        Result(state=State.UNKNOWN, summary="Agent plugin reported an error: boom")
    ]
    assert _results({"query_error_state": 2}, section)[0].state is State.CRIT
