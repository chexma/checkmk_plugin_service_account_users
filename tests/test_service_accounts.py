# Copyright (C) 2026 Andre Eckstein - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the plugin family service_accounts. All names are fictional."""

from pathlib import Path

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa
from cmk_addons.plugins.service_accounts.bakery import service_accounts as bakery
from cmk_addons.plugins.service_accounts.graphing import service_accounts as graphing
from cmk_addons.plugins.service_accounts.inventory_ui import service_accounts as inventory_ui
from cmk_addons.plugins.service_accounts.rulesets import agent_config
from cmk_addons.plugins.service_accounts.rulesets import inventory as inventory_rules
from cmk_addons.plugins.service_accounts.rulesets import service_accounts as rules

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


def _notices(params, section) -> dict[str, State]:
    """Summary text -> state of all results that are not OK."""
    return {r.summary: r.state for r in _results(params, section) if r.state is not State.OK}


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
        ("", "no_account"),
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


def test_discovery_stores_all_services(section) -> None:
    assert _discovered(section) == {
        "discovered_services": {
            "Spooler": {"account": "LocalSystem", "sid": "S-1-5-18"},
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


def test_discovery_leaves_out_services_without_account() -> None:
    # Per-user service instances have no account and a new name with every logon.
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01", MACHINE_SID],
            ["service", "Spooler", "Print Spooler", "LocalSystem", "S-1-5-18", "Auto", "Running"],
            ["service", "CDPUserSvc_1a2b3", "Connected Devices", "", "", "Auto", "Running"],
        ]
    )
    assert list(_discovered(section)["discovered_services"]) == ["Spooler"]


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


def test_service_name() -> None:
    assert sa.check_plugin_service_accounts.service_name == "Windows Service Accounts"


def test_default_is_warn_for_accounts_that_are_not_allowed(section) -> None:
    # Checkmk passes these parameters if no rule matches.
    defaults = sa.check_plugin_service_accounts.check_default_parameters
    assert defaults == {"not_allowed_state": 1}
    assert set(_notices(defaults, section).values()) == {State.WARN}
    assert len(_notices(defaults, section)) == 4
    # A rule can switch it off again.
    assert _notices({**defaults, "not_allowed_state": 0}, section) == {}


def test_check_details_have_one_line_per_service(section) -> None:
    details = [r.details for r in _results({}, section)]
    assert (
        "MSSQLSERVER (SQL Server): CONTOSO\\svc_sql (domain account), Auto, Running\n"
        "SQLAgent (SQL Server Agent): CONTOSO\\svc_sql (domain account), Manual, Stopped"
    ) in details
    assert "Legacy (Legacy App): CONTOSO\\old_admin (domain account), Auto, Stopped" in details


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


# --- check: allow list and unwanted accounts --------------------------------


def test_service_without_account_is_built_in_by_default() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01", MACHINE_SID],
            ["service", "A", "A", "", "", "Manual", "Stopped"],
        ]
    )
    assert _results({"not_allowed_state": 1}, section)[0].summary == (
        "0 services under 0 service accounts"
    )
    params = {"not_allowed_state": 1, "builtin_kinds": ["local_system"]}
    results = _results(params, section)
    assert results[0].summary == "1 service under 1 service account"
    assert results[1].state is State.WARN
    assert results[1].summary == "(no account): not on the allow list (1 service)"


def test_not_allowed_state_applies_to_every_reported_account(section) -> None:
    assert _notices({"not_allowed_state": 1}, section) == {
        ".\\backup: not on the allow list (1 service)": State.WARN,
        "CONTOSO\\gmsa_web$: not on the allow list (1 service)": State.WARN,
        "CONTOSO\\old_admin: not on the allow list (1 service)": State.WARN,
        "CONTOSO\\svc_sql: not on the allow list (2 services)": State.WARN,
    }


def test_allowed_and_allowed_additional_are_combined(section) -> None:
    params = {
        "not_allowed_state": 2,
        "allowed": ["CONTOSO\\\\svc_.*", "contoso\\\\gmsa_web\\$"],
        "allowed_additional": ["\\$HOSTNAME\\$-is-literal", "$HOSTNAME$\\\\backup"],
    }
    assert _notices(params, section) == {
        "CONTOSO\\old_admin: not on the allow list (1 service)": State.CRIT,
    }


def test_allowed_matches_the_whole_account_only(section) -> None:
    notices = _notices({"not_allowed_state": 1, "allowed": ["CONTOSO\\\\svc"]}, section)
    assert "CONTOSO\\svc_sql: not on the allow list (2 services)" in notices


def test_allowed_matches_the_sid(section) -> None:
    params = {"not_allowed_state": 1, "allowed": [DOMAIN_SID + "-.*"]}
    assert set(_notices(params, section)) == {
        ".\\backup: not on the allow list (1 service)",
        "CONTOSO\\old_admin: not on the allow list (1 service)",
    }


def test_hostname_placeholder_is_escaped() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV.APP01", ""],
            ["service", "A", "A", "SRVXAPP01\\backup", "", "Auto", "Running"],
            ["service", "B", "B", "SRV.APP01\\backup", "", "Auto", "Running"],
        ]
    )
    params = {"not_allowed_state": 1, "allowed": ["$HOSTNAME$\\\\backup"]}
    assert set(_notices(params, section)) == {
        "SRVXAPP01\\backup: not on the allow list (1 service)"
    }


def test_forbidden_first_match_wins_and_allow_list_exempts(section) -> None:
    params = {
        "allowed": ["CONTOSO\\\\svc_sql"],
        "forbidden": [
            {"pattern": ".*admin.*", "state": 2},
            {"pattern": "CONTOSO\\\\.*", "state": 1},
        ],
    }
    assert _notices(params, section) == {
        "CONTOSO\\gmsa_web$: unwanted account (1 service)": State.WARN,
        "CONTOSO\\old_admin: unwanted account (1 service)": State.CRIT,
    }


def test_forbidden_and_not_allowed_take_the_worst_state(section) -> None:
    params = {"not_allowed_state": 2, "forbidden": [{"pattern": ".*admin.*", "state": 1}]}
    assert (
        _notices(params, section)[
            "CONTOSO\\old_admin: unwanted account, not on the allow list (1 service)"
        ]
        is State.CRIT
    )


def test_invalid_pattern_is_reported_and_does_not_crash(section) -> None:
    params = {"allowed": ["CONTOSO\\\\(svc"], "forbidden": [{"pattern": "[", "state": 2}]}
    assert _notices(params, section) == {
        "Invalid pattern in rule: CONTOSO\\\\(svc": State.UNKNOWN,
        "Invalid pattern in rule: [": State.UNKNOWN,
    }


def test_allow_entry_for_a_service_applies_to_that_service_only(section) -> None:
    # CONTOSO\svc_sql may run MSSQLSERVER, but it also runs SQLAgent.
    params = {
        "not_allowed_state": 1,
        "allowed": [
            {"service": "mssqlserver", "account": "CONTOSO\\\\svc_sql"},
            {"account": "CONTOSO\\\\(gmsa_web\\$|old_admin)"},
            {"service": "Backup", "account": "$HOSTNAME$\\\\backup"},
        ],
    }
    assert _notices(params, section) == {
        "CONTOSO\\svc_sql: not on the allow list (1 of 2 services)": State.WARN,
    }
    details = [r.details for r in _results(params, section)]
    assert (
        "MSSQLSERVER (SQL Server): CONTOSO\\svc_sql (domain account), Auto, Running\n"
        "SQLAgent (SQL Server Agent): CONTOSO\\svc_sql (domain account), Manual, Stopped: "
        "not on the allow list"
    ) in details


def test_allow_entry_service_pattern_matches_the_whole_name(section) -> None:
    params = {
        "not_allowed_state": 1,
        "allowed": [{"service": "SQL", "account": "CONTOSO\\\\svc_sql"}],
    }
    assert "CONTOSO\\svc_sql: not on the allow list (2 services)" in _notices(params, section)
    params["allowed"] = [{"service": ".*SQL.*", "account": "CONTOSO\\\\svc_sql"}]
    assert not [n for n in _notices(params, section) if "svc_sql" in n]


def test_allow_entries_of_both_lists_and_of_the_old_format_are_combined(section) -> None:
    # Rules saved before 2.5.3 hold plain account patterns.
    params = {
        "not_allowed_state": 1,
        "allowed": ["CONTOSO\\\\gmsa_web\\$", {"service": "", "account": "CONTOSO\\\\old_admin"}],
        "allowed_additional": [{"service": "MSSQLSERVER|SQLAgent", "account": ".*svc_sql"}],
    }
    assert set(_notices(params, section)) == {".\\backup: not on the allow list (1 service)"}


def test_unwanted_account_is_checked_if_one_of_its_services_is_not_allowed(section) -> None:
    params = {
        "allowed": [{"service": "MSSQLSERVER", "account": "CONTOSO\\\\svc_sql"}],
        "forbidden": [{"pattern": ".*svc_sql", "state": 2}],
    }
    assert _notices(params, section) == {
        "CONTOSO\\svc_sql: unwanted account (1 of 2 services)": State.CRIT
    }
    params["allowed"] = [{"service": "MSSQLSERVER|SQLAgent", "account": "CONTOSO\\\\svc_sql"}]
    assert _notices(params, section) == {}


def test_invalid_service_pattern_is_reported(section) -> None:
    params = {"allowed": [{"service": "(", "account": ".*"}]}
    assert _notices(params, section) == {"Invalid pattern in rule: (": State.UNKNOWN}


def test_account_with_two_spellings_is_matched_under_each_of_them() -> None:
    section = sa.parse_service_accounts(
        _table(
            f"computer|SRV-APP01|{MACHINE_SID}\n"
            f"service|A|A|svc_sql@contoso.example|{DOMAIN_SID}-1105|Auto|Running\n"
            f"service|B|B|CONTOSO\\svc_sql|{DOMAIN_SID}-1105|Auto|Running"
        )
    )
    params = {"not_allowed_state": 2, "allowed": ["CONTOSO\\\\svc_.*"]}
    assert _notices(params, section) == {}
    assert _results(params, section)[1].details == (
        "A (A): svc_sql@contoso.example (domain account), Auto, Running\n"
        "B (B): CONTOSO\\svc_sql (domain account), Auto, Running"
    )


def test_sid_pattern_uses_the_baseline_sid_if_the_translation_failed(section) -> None:
    # Domain not reachable: the agent sends the account without SID this time.
    unresolved = _with(
        "MSSQLSERVER|SQL Server|CONTOSO\\svc_sql||Auto|Running",
        "SQLAgent|SQL Server Agent|CONTOSO\\svc_sql||Manual|Stopped",
    )
    params = {"not_allowed_state": 1, "allowed": [f"{DOMAIN_SID}-1105"], **_discovered(section)}
    assert "CONTOSO\\svc_sql: not on the allow list (2 services)" not in _notices(
        params, unresolved
    )


def test_details_name_the_reason(section) -> None:
    params = {"not_allowed_state": 1, "forbidden": [{"pattern": ".*admin.*", "state": 2}]}
    details = [r.details for r in _results(params, section)]
    assert (
        "Legacy (Legacy App): CONTOSO\\old_admin (domain account), Auto, Stopped: "
        "unwanted account, not on the allow list"
    ) in details


def _many_accounts(count: int) -> sa.Section:
    return _with(
        *(f"App{i:02}|App {i:02}|CONTOSO\\svc_app{i:02}||Auto|Running" for i in range(count))
    )


def test_summary_names_at_most_ten_findings(section) -> None:
    params = {
        "not_allowed_state": 1,
        "allowed": ["CONTOSO\\\\(svc_sql|gmsa_web\\$|old_admin)", ".*backup"],
    }
    not_ok = [r for r in _results(params, _many_accounts(13)) if r.state is not State.OK]
    assert len(not_ok) == 11
    assert not_ok[9].summary == "CONTOSO\\svc_app09: not on the allow list (1 service)"
    assert not_ok[10].state is State.WARN
    assert not_ok[10].summary == "3 more findings (see details)"
    assert not_ok[10].details == (
        "App10 (App 10): CONTOSO\\svc_app10 (domain account), Auto, Running: "
        "not on the allow list(!)\n"
        "App11 (App 11): CONTOSO\\svc_app11 (domain account), Auto, Running: "
        "not on the allow list(!)\n"
        "App12 (App 12): CONTOSO\\svc_app12 (domain account), Auto, Running: "
        "not on the allow list(!)"
    )


def test_summary_names_the_worst_findings_first(section) -> None:
    params = {
        "not_allowed_state": 1,
        "forbidden": [{"pattern": ".*svc_app12", "state": 2}],
        "allowed": ["CONTOSO\\\\(svc_sql|gmsa_web\\$|old_admin)", ".*backup"],
    }
    not_ok = [r for r in _results(params, _many_accounts(13)) if r.state is not State.OK]
    assert not_ok[0].state is State.CRIT
    assert not_ok[0].summary.startswith("CONTOSO\\svc_app12: unwanted account")
    assert not_ok[10].state is State.WARN


# --- check: changes since the discovery -------------------------------------

CHANGES = {"added": 1, "changed": 2, "removed": 3}


def _with(*lines: str) -> sa.Section:
    """STRING_TABLE with services replaced or added (by name).

    A line is "name|display name|account|SID|start mode|state"."""
    new = [["service", *line.split("|")] for line in lines]
    names = {line[1] for line in new}
    section = sa.parse_service_accounts(
        [line for line in STRING_TABLE if line[0] != "service" or line[1] not in names] + new
    )
    assert section is not None
    return section


def _without(*names: str) -> sa.Section:
    """STRING_TABLE without the named services."""
    section = sa.parse_service_accounts([line for line in STRING_TABLE if line[1] not in names])
    assert section is not None
    return section


def test_no_changes_no_findings(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, section) == {}


def test_changes_need_the_rule(section) -> None:
    changed = _with("New|New|CONTOSO\\svc_new||Auto|Running")
    assert _notices(_discovered(section), changed) == {}


def test_changes_need_a_baseline(section) -> None:
    assert _notices({"changes": CHANGES}, section) == {}


def test_added_service(section) -> None:
    changed = _with(
        "New|New|CONTOSO\\svc_new||Auto|Running",
        "NewSystem|New System|LocalSystem|S-1-5-18|Auto|Running",
        "NewVirtual|New Virtual|NT SERVICE\\NewVirtual|S-1-5-80-9|Auto|Running",
    )
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, changed) == {"New service New runs as CONTOSO\\svc_new": State.WARN}


def test_added_service_under_an_allowed_account_is_not_reported(section) -> None:
    changed = _with("New|New|CONTOSO\\svc_new||Auto|Running")
    params = {"changes": CHANGES, "allowed": ["CONTOSO\\\\svc_.*"], **_discovered(section)}
    assert _notices(params, changed) == {}


def test_service_changed_from_local_system_is_a_change(section) -> None:
    changed = _with("Spooler|Print Spooler|CONTOSO\\svc_x||Auto|Running")
    params = {"changes": {"changed": 2}, **_discovered(section)}
    assert _notices(params, changed) == {
        "Account of service Spooler changed from LocalSystem to CONTOSO\\svc_x": State.CRIT
    }


def test_local_system_not_built_in_does_not_report_known_services_as_added(section) -> None:
    params = {"changes": CHANGES, "builtin_kinds": ["virtual"], **_discovered(section)}
    assert _notices(params, section) == {}


def test_services_without_account_are_left_out_of_the_change_detection(section) -> None:
    changed = _with("CDPUserSvc_1a2b3|Connected Devices|||Auto|Running")
    params = {"changes": CHANGES, "builtin_kinds": ["local_system"], **_discovered(section)}
    assert _notices(params, changed) == {}


def test_changed_account(section) -> None:
    changed = _with(
        # service account -> other service account
        f"MSSQLSERVER|SQL Server|CONTOSO\\svc_other|{DOMAIN_SID}-1200|Auto|Running",
        # service account -> built-in
        "WebApp|Web App|LocalSystem|S-1-5-18|Auto|Running",
        # built-in -> service account
        f"Dhcp|DHCP Client|CONTOSO\\svc_dhcp|{DOMAIN_SID}-1201|Auto|Running",
        # built-in -> built-in: not reported
        "Dnscache|DNS Client|NT AUTHORITY\\LocalService|S-1-5-19|Auto|Running",
    )
    params = {"changes": CHANGES, **_discovered(section)}
    prefix = "Account of service"
    assert _notices(params, changed) == {
        f"{prefix} Dhcp changed from NT AUTHORITY\\LocalService to CONTOSO\\svc_dhcp": State.CRIT,
        f"{prefix} MSSQLSERVER changed from CONTOSO\\svc_sql to CONTOSO\\svc_other": State.CRIT,
        f"{prefix} WebApp changed from CONTOSO\\gmsa_web$ to LocalSystem": State.CRIT,
    }


def test_unresolved_sid_is_not_a_change(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    # Domain not reachable: same name, the SID could not be translated this time.
    assert _notices(params, _with("MSSQLSERVER|SQL Server|contoso\\SVC_SQL||Auto|Running")) == {}
    # The other way round: the baseline has no SID, now there is one.
    changed = _with(f"Legacy|Legacy App|CONTOSO\\old_admin|{DOMAIN_SID}-1300|Auto|Stopped")
    assert _notices(params, changed) == {}


def test_renamed_account_with_the_same_sid_is_not_a_change(section) -> None:
    changed = _with(f"WebApp|Web App|CONTOSO\\gmsa_web2$|{DOMAIN_SID}-1106|Auto|Running")
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, changed) == {}


def test_removed_service(section) -> None:
    params = {"changes": CHANGES, **_discovered(section)}
    # Dhcp ran under a built-in account: its removal is not reported.
    assert _notices(params, _without("Legacy", "Dhcp")) == {
        "Service Legacy (CONTOSO\\old_admin) no longer exists": State.UNKNOWN
    }


def test_only_configured_changes_are_reported(section) -> None:
    table = [line for line in STRING_TABLE if line[1] != "Legacy"]
    table.append("service|New|New|CONTOSO\\svc_new||Auto|Running".split("|"))
    params = {"changes": {"removed": 1}, **_discovered(section)}
    assert _notices(params, sa.parse_service_accounts(table)) == {
        "Service Legacy (CONTOSO\\old_admin) no longer exists": State.WARN
    }


def test_ignore_disabled_skips_changes_of_disabled_services(section) -> None:
    changed = _with("Backup|Backup Service|CONTOSO\\svc_x||Disabled|Stopped")
    params = {"changes": CHANGES, "ignore_disabled": True, **_discovered(section)}
    assert _notices(params, changed) == {}
    assert len(_notices({**params, "ignore_disabled": False}, changed)) == 1


def test_no_change_detection_while_the_plugin_reports_an_error(section) -> None:
    broken = sa.parse_service_accounts([["computer", "SRV-APP01", MACHINE_SID], ["error", "boom"]])
    params = {"changes": CHANGES, **_discovered(section)}
    assert list(_notices(params, broken)) == ["Agent plugin reported an error: boom"]


def test_change_to_an_account_allowed_for_another_service_only_is_reported(section) -> None:
    allowed = [{"service": "MSSQLSERVER|SQLAgent", "account": "CONTOSO\\\\svc_sql"}]
    params = {"changes": CHANGES, "allowed": allowed, **_discovered(section)}
    changed = _with(f"Spooler|Print Spooler|CONTOSO\\svc_sql|{DOMAIN_SID}-1105|Auto|Running")
    assert _notices(params, changed) == {
        "Account of service Spooler changed from LocalSystem to CONTOSO\\svc_sql": State.CRIT
    }
    params["allowed"] = [{"account": "CONTOSO\\\\svc_sql"}]
    assert _notices(params, changed) == {}


def test_changes_without_a_baseline_are_announced(section) -> None:
    summaries = [r.summary for r in _results({"changes": CHANGES}, section)]
    assert "No change detection: no baseline, run the service discovery" in summaries
    assert all("baseline" not in r.summary for r in _results({}, section))


def test_recreated_account_shows_the_sids(section) -> None:
    changed = _with(f"WebApp|Web App|CONTOSO\\gmsa_web$|{DOMAIN_SID}-1999|Auto|Running")
    params = {"changes": CHANGES, **_discovered(section)}
    assert list(_notices(params, changed)) == [
        f"Account of service WebApp changed from CONTOSO\\gmsa_web$ ({DOMAIN_SID}-1106) "
        f"to CONTOSO\\gmsa_web$ ({DOMAIN_SID}-1999)"
    ]


def test_malformed_baseline_does_not_crash(section) -> None:
    baseline = {"Legacy": "CONTOSO\\old_admin", "WebApp": {"account": "CONTOSO\\gmsa_web$"}}
    params = {"changes": CHANGES, "discovered_services": baseline}
    assert all(isinstance(r.summary, str) for r in _results(params, section))
    assert not [
        r
        for r in _results({"changes": CHANGES, "discovered_services": "x"}, section)
        if r.state is not State.OK
    ]


# --- inventory --------------------------------------------------------------


INVENTORY_DEFAULTS = sa.inventory_plugin_service_accounts.inventory_default_parameters


def test_inventory_default_leaves_out_built_in_accounts() -> None:
    assert INVENTORY_DEFAULTS == {"all_services": False}


def test_inventory_can_list_all_services(section) -> None:
    rows = list(sa.inventory_service_accounts({"all_services": True}, section))
    assert len(rows) == len(section.services)
    assert rows[0].key_columns == {"service": "Spooler"}
    assert rows[0].inventory_columns["kind"] == "local_system"


def test_inventory_rule_form_builds() -> None:
    plugin = sa.inventory_plugin_service_accounts
    assert (
        plugin.inventory_ruleset_name == inventory_rules.rule_spec_service_accounts_inventory.name
    )
    form = inventory_rules.rule_spec_service_accounts_inventory.parameter_form()
    assert set(form.elements) == set(INVENTORY_DEFAULTS)


def test_inventory_rows(section) -> None:
    rows = list(sa.inventory_service_accounts(INVENTORY_DEFAULTS, section))
    assert [r.key_columns["service"] for r in rows] == [
        "MSSQLSERVER",
        "SQLAgent",
        "Backup",
        "WebApp",
        "Legacy",
    ]
    assert rows[2] == TableRow(
        path=["software", "os", "service_accounts"],
        key_columns={"service": "Backup"},
        inventory_columns={
            "display_name": "Backup Service",
            "account": ".\\backup",
            "kind": "local_user",
            "start_mode": "Disabled",
        },
        status_columns={"state": "Stopped"},
    )


def test_inventory_ui_knows_every_column(section) -> None:
    row = next(iter(sa.inventory_service_accounts(INVENTORY_DEFAULTS, section)))
    node = inventory_ui.node_software_os_service_accounts
    assert node.title.localize(lambda x: x) == "Windows Service Accounts"
    assert node.table.view.title.localize(lambda x: x) == "Windows Service Accounts"
    assert list(node.path) == row.path
    assert set(node.table.columns) == {
        *row.key_columns,
        *row.inventory_columns,
        *row.status_columns,
    }
    assert set(node.table.columns["kind"].mapping) == set(sa.KIND_TITLES)


# --- rule forms -------------------------------------------------------------


def test_check_rule_form_builds() -> None:
    form = rules.rule_spec_service_accounts.parameter_form()
    assert set(form.elements) == {
        "builtin_kinds",
        "ignore_disabled",
        "allowed",
        "allowed_additional",
        "not_allowed_state",
        "forbidden",
        "changes",
        "query_error_state",
    }
    assert tuple(form.elements["builtin_kinds"].parameter_form.prefill.value) == (
        sa.DEFAULT_BUILTIN_KINDS
    )
    kinds = {e.name for e in form.elements["builtin_kinds"].parameter_form.elements}
    assert kinds == set(sa.KIND_TITLES)


def test_allow_list_entries_have_service_and_account_and_migrate_old_rules() -> None:
    form = rules.rule_spec_service_accounts.parameter_form()
    for name in ("allowed", "allowed_additional"):
        entry = form.elements[name].parameter_form.element_template
        assert list(entry.elements) == ["service", "account"]
        assert not entry.elements["service"].required
        assert entry.elements["account"].required
        assert entry.migrate("CONTOSO\\\\svc_.*") == {"account": "CONTOSO\\\\svc_.*"}
        assert entry.migrate({"service": "A", "account": "B"}) == {"service": "A", "account": "B"}


def test_check_rule_form_prefills_the_default_state() -> None:
    form = rules.rule_spec_service_accounts.parameter_form()
    defaults = sa.check_plugin_service_accounts.check_default_parameters
    assert form.elements["not_allowed_state"].parameter_form.prefill.value == (
        defaults["not_allowed_state"]
    )


def test_check_rule_form_ignores_the_discovered_baseline() -> None:
    # The discovery page validates the effective parameters with this form.
    form = rules.rule_spec_service_accounts.parameter_form()
    assert "discovered_services" in form.ignored_elements


def test_graphing_uses_the_metrics_of_the_check(section) -> None:
    yielded = {m.name for m in sa.check_service_accounts({}, section) if isinstance(m, Metric)}
    assert yielded == {
        graphing.metric_service_account_services.name,
        graphing.metric_service_account_accounts.name,
    }
    assert set(graphing.graph_service_accounts.simple_lines) == yielded
    assert set(graphing.perfometer_service_accounts.segments) <= yielded


# --- bakery -----------------------------------------------------------------


def test_bakery_rule_form_builds() -> None:
    form = agent_config.rule_spec_service_accounts_bakery.parameter_form()
    assert set(form.elements) == {"deployment", "interval"}
    assert agent_config.rule_spec_service_accounts_bakery.name == (
        bakery.bakery_plugin_service_accounts.name
    )


def _bake(rule: dict) -> list:
    plugin = bakery.bakery_plugin_service_accounts
    return list(plugin.files_function(plugin.parameter_parser(rule)))


def test_bakery_deploys_the_windows_plugin() -> None:
    (plugin,) = _bake({"deployment": ("deploy", None)})
    assert str(plugin.base_os) == "windows"
    assert str(plugin.source) == "service_accounts.ps1"
    assert plugin.interval is None


def test_bakery_interval() -> None:
    (plugin,) = _bake({"deployment": ("deploy", None), "interval": 3600.0})
    assert plugin.interval == 3600


def test_bakery_do_not_deploy() -> None:
    assert not _bake({"deployment": ("do_not_deploy", None), "interval": 3600.0})


def test_agent_plugin_exists_and_is_ascii() -> None:
    # The bakery takes the source from the family's agents/ directory. Windows
    # PowerShell 5.1 reads a script without BOM in the ANSI code page.
    (plugin,) = _bake({"deployment": ("deploy", None)})
    source = Path(bakery.__file__).parent.parent / "agents" / plugin.source
    assert source.read_bytes().isascii()
    assert "<<<service_accounts:sep(124)>>>" in source.read_text()
