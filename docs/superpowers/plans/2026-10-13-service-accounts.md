# Service Accounts Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Checkmk plugin `service_accounts`: one service per Windows host that shows which Windows services run under a service account and alerts on accounts that are not allowed, plus an inventory table, with the agent plugin deployed through the agent bakery.

**Architecture:** A PowerShell agent plugin reports every Windows service with its account and the account's SID, unfiltered. All evaluation (account kinds, allow list, unwanted accounts, changes since the discovery) happens in one check plugin on the server, so a rule change never requires baking. The same section feeds an inventory table with a view for cross-host searches.

**Tech Stack:** Checkmk 2.5 (`cmk.agent_based.v2`, `cmk.rulesets.v1`, `cmk.graphing.v1`, `cmk.bakery.v2_unstable`, `cmk.inventory_ui.v1_unstable`), Python 3.13, pytest, PowerShell 5.1.

**Spec:** `docs/superpowers/specs/2026-10-13-service-accounts-design.md`. Read it before starting.

## Global Constraints

- Target: Checkmk 2.5 (devcontainer: `ultimate` 2.5.0p15). Windows hosts only.
- All plugin files live in `plugins/service_accounts/` (bind-mounted to `~/local/lib/python3/cmk_addons/plugins/service_accounts/`). No `__init__.py` files: plugin families are namespace packages.
- Section header is exactly `<<<service_accounts:sep(124)>>>`. The agent plugin has no configuration file and reports all services unfiltered.
- The bakery (API v2) takes the plugin source from the family's `agents/` directory, not from `agents/windows/plugins/`.
- Without a rule the service `Service Accounts` is always OK.
- Regexes are full-match and case-insensitive, tried against the account name and the SID. `$HOSTNAME$` is replaced by the escaped computer name from the `computer` line.
- Test data uses fictional names only (CONTOSO, SRV-APP01, round SIDs such as `S-1-5-21-1000-2000-3000`). This also holds for files in `temp/` and for hosts in the dev site. Never copy real host, domain or account names or SIDs anywhere.
- `cmk.bakery.v2_unstable` and `cmk.inventory_ui.v1_unstable` are unstable APIs (stable in 3.0.0). Use them as shown; do not fall back to the bakery API v1.
- Formatting: black and isort with line length 100 (`pyproject.toml`), flake8 clean (`.flake8`). In Claude Code a hook formats every edited Python file; otherwise run `black plugins/ tests/ && isort plugins/ tests/` before each commit.
- Do not build an MKP and do not create the `package` manifest: that happens only on explicit request. Never run `mkp release` or `mkp disable`. Never create symlinks in `~/local`.
- `List` form specs take no `prefill` argument.
- The code blocks in this plan were run against Checkmk 2.5.0p15: all 50 tests pass with the code as written. If a test fails, look for a transcription error before changing the code or the test.

## Decisions beyond the spec

The spec leaves these points open. The plan settles them as follows; Task 9 records them in the spec.

1. `discovered_services` maps a service name to `{"account": <name>, "sid": <SID or "">}` instead of to a single string. Two accounts are the same if their SIDs are equal; if either side has no SID, the names are compared ignoring case. Otherwise a domain that is unreachable for one agent run (SID empty) would look like a changed account.
2. A pattern is also tried against `<computer name>\name` when the service is configured with `.\name`, so `$HOSTNAME$\\backup` matches the local user however it was entered.
3. A pattern that is not a valid regular expression yields an UNKNOWN result naming the pattern; the check does not crash.
4. With `ignore_disabled`, disabled services are also left out of the change detection.
5. If the agent plugin reports an error at discovery time, the service is created without a baseline, and the check skips the change detection while there is no baseline or while the plugin reports an error.
6. Known limitations, documented in the checkman page: computer accounts (`DOMAIN\HOST$`) are classified as `managed`; on a domain controller the machine SID is the domain SID, so domain accounts are classified as `local_user`; a UPN that cannot be translated to a SID is classified as `domain`.

## Review Focus

Inputs the spec implies but does not spell out, each pinned by a test:

1. The SID of an account cannot be translated on one agent run but could before (domain controller not reachable): no `changed` finding. Test `test_unresolved_sid_is_not_a_change`, Task 5.
2. A rule contains an invalid regular expression: UNKNOWN result, no crash. Test `test_invalid_pattern_is_reported_and_does_not_crash`, Task 4.
3. Agent output with short lines, empty fields, unknown line types or a service without a name: the parser keeps what is usable. Test `test_parse_empty_and_missing_fields`, Task 1.
4. The machine SID is empty, or another SID merely starts with the same characters: local users are still recognised by name, and `...-3000` is not a prefix of `...-30001-500`. Tests `test_classify_without_machine_sid_uses_the_name_for_local_users` and `test_classify_machine_sid_is_not_a_string_prefix`, Task 2.
5. The discovery runs while the agent plugin reports an error: no empty baseline that later turns every service into an `added` finding. Tests `test_discovery_on_error_has_no_baseline` (Task 3) and `test_changes_need_a_baseline` (Task 5).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `plugins/service_accounts/agent_based/service_accounts.py` | Section parser, account classification, discovery, check, inventory plugin | 1 to 6 |
| `plugins/service_accounts/inventory_ui/service_accounts.py` | Titles and view of the inventory table | 6 |
| `plugins/service_accounts/rulesets/service_accounts.py` | Check parameters rule | 7 |
| `plugins/service_accounts/graphing/service_accounts.py` | Metrics, graph, perfometer | 7 |
| `plugins/service_accounts/agents/service_accounts.ps1` | Agent plugin | 8 |
| `plugins/service_accounts/rulesets/agent_config.py` | Bakery rule | 8 |
| `plugins/service_accounts/bakery/service_accounts.py` | Bakery plugin | 8 |
| `plugins/service_accounts/checkman/service_accounts` | Man page | 9 |
| `tests/test_service_accounts.py` | All tests | 1 to 8 |

The check logic stays in one module: parser, classification and check share the `Section` type and are small enough to read together.

Run a single test file with `pytest tests/test_service_accounts.py -q`. The tests import the plugin as `cmk_addons.plugins.service_accounts...`; this works because `plugins/` is mounted into the site.

---

### Task 1: Section parser

**Files:**
- Create: `plugins/service_accounts/agent_based/service_accounts.py`
- Create: `tests/test_service_accounts.py`
- Delete: `plugins/service_accounts/.gitkeep`, `tests/.gitkeep`

**Interfaces:**
- Produces: `WinService(name, display_name, account, sid, start_mode, state)` and `Section(computer, machine_sid, services, error)` (frozen dataclasses, all fields `str` except `services: Sequence[WinService]` and `error: str | None`), `parse_service_accounts(string_table) -> Section | None`, `agent_section_service_accounts`.
- Test helpers produced: `MACHINE_SID`, `DOMAIN_SID`, `AGENT_OUTPUT`, `_table(text)`, `STRING_TABLE`, fixture `section`.

- [ ] **Step 1: Create a branch**

```bash
git switch -c implement-service-accounts
git rm -q plugins/service_accounts/.gitkeep tests/.gitkeep
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_service_accounts.py`:

```python
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
```

`STRING_TABLE` holds nine services: one Local System, one Local Service, one Network Service (German name), one virtual account, two under `CONTOSO\svc_sql`, one disabled under the local user `.\backup`, one under a managed account, one under a domain account without SID.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'cmk_addons.plugins.service_accounts'`

- [ ] **Step 4: Write the parser**

Create `plugins/service_accounts/agent_based/service_accounts.py`:

```python
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
```

The agent separates fields with pipes, so Checkmk passes each line as a list of strings and keeps empty fields. A `service` line is padded to six values; a line without a service name is dropped.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `5 passed`

- [ ] **Step 6: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Add section parser for service_accounts"
```

---

### Task 2: Account classification

**Files:**
- Modify: `plugins/service_accounts/agent_based/service_accounts.py` (append)
- Modify: `tests/test_service_accounts.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1 except the test constants `MACHINE_SID`, `DOMAIN_SID`.
- Produces: `DEFAULT_BUILTIN_KINDS: tuple[str, ...]`, `KIND_TITLES: dict[str, str]` (keys are the eight kinds), `classify(account: str, sid: str, computer: str, machine_sid: str) -> str` returning one of `local_system`, `local_service`, `network_service`, `virtual`, `local_user`, `managed`, `domain`, `unknown`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_service_accounts.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `26 failed, 5 passed in 0.19s`, every failure is `AttributeError: module ... has no attribute 'classify'`

- [ ] **Step 3: Implement the classification**

Append to `plugins/service_accounts/agent_based/service_accounts.py` (after `agent_section_service_accounts`):

```python
DEFAULT_BUILTIN_KINDS = ("local_system", "local_service", "network_service", "virtual")


KIND_TITLES = {
    "local_system": "Local System",
    "local_service": "Local Service",
    "network_service": "Network Service",
    "virtual": "virtual account",
    "local_user": "local user",
    "managed": "managed service account",
    "domain": "domain account",
    "unknown": "unknown account",
}


_WELL_KNOWN_SIDS = {
    "S-1-5-18": "local_system",
    "S-1-5-19": "local_service",
    "S-1-5-20": "network_service",
}


_WELL_KNOWN_NAMES = {
    "localsystem": "local_system",
    ".\\localsystem": "local_system",
    "nt authority\\system": "local_system",
    "nt authority\\localservice": "local_service",
    "nt authority\\local service": "local_service",
    "nt authority\\networkservice": "network_service",
    "nt authority\\network service": "network_service",
}


def _is_local_name(account: str, computer: str) -> bool:
    domain, sep, _user = account.partition("\\")
    return bool(sep) and (domain == "." or (bool(computer) and domain.lower() == computer.lower()))


def classify(account: str, sid: str, computer: str, machine_sid: str) -> str:
    """Return the kind of an account, by SID if there is one, otherwise by name."""
    sid = sid.upper()
    if sid:
        if sid in _WELL_KNOWN_SIDS:
            return _WELL_KNOWN_SIDS[sid]
        if sid.startswith("S-1-5-80-"):
            return "virtual"
        if not sid.startswith("S-1-5-21-"):
            return "unknown"
        if machine_sid:
            if sid.startswith(machine_sid.upper() + "-"):
                return "local_user"
        elif _is_local_name(account, computer):
            return "local_user"
        return "managed" if account.endswith("$") else "domain"

    name = account.lower()
    if name in _WELL_KNOWN_NAMES:
        return _WELL_KNOWN_NAMES[name]
    if name.startswith("nt service\\"):
        return "virtual"
    if _is_local_name(account, computer):
        return "local_user"
    if "\\" in account:
        return "managed" if account.endswith("$") else "domain"
    if "@" in account:
        return "domain"
    return "unknown"
```

With a SID the name only decides between `managed` and `domain` (trailing `$`) and, if the machine SID is unknown, whether the account is local. Without a SID only the English well-known names from the spec are recognised; localized names such as `NT-AUTORITÄT\Netzwerkdienst` always come with a SID because well-known accounts can be translated without a domain controller.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `31 passed`

- [ ] **Step 5: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Classify service accounts by SID and by name"
```

---

### Task 3: Discovery and the summary check

**Files:**
- Modify: `plugins/service_accounts/agent_based/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: `Section`, `WinService`, `classify`, `DEFAULT_BUILTIN_KINDS`, `KIND_TITLES`.
- Produces: `account_key(account, sid) -> str`, `discover_service_accounts(section) -> DiscoveryResult` (one `Service` whose parameters are `{"discovered_services": {<service name>: {"account": str, "sid": str}}}`, or `Service()` without parameters on a plugin error), `check_service_accounts(params, section) -> CheckResult`, `check_plugin_service_accounts` (ruleset name `service_accounts`), metrics `service_account_services` and `service_account_accounts`. Private helpers used by later tasks: `_Account` (fields `name`, `sid`, `kind`, `services`), `_group_accounts`, `_account_details`, `_display(account) -> str`, `_plural(count, word) -> str`.
- Test helpers produced: `_results(params, section) -> list[Result]`, `_discovered(section) -> dict`.

This task handles the parameters `builtin_kinds`, `ignore_disabled` and `query_error_state`. Every account result is OK here; Task 4 adds the states.

- [ ] **Step 1: Write the failing tests**

In `tests/test_service_accounts.py` the imports now read:

```python
import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa
```

Add these helpers after the `section` fixture:

```python
def _results(params, section) -> list[Result]:
    return [r for r in sa.check_service_accounts(params, section) if isinstance(r, Result)]


def _discovered(section) -> dict:
    (service,) = sa.discover_service_accounts(section)
    return dict(service.parameters)
```

Append:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `10 failed, 31 passed in 0.27s` (`AttributeError`: `discover_service_accounts` and `check_service_accounts` do not exist)

- [ ] **Step 3: Implement discovery and check**

In `plugins/service_accounts/agent_based/service_accounts.py` the imports now read:

```python
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    Metric,
    Result,
    Service,
    State,
    StringTable,
)
```

Append after `classify`:

```python
def account_key(account: str, sid: str) -> str:
    """Identity of an account: the SID if known, else the lower-case name."""
    return sid.upper() or account.lower()


def discover_service_accounts(section: Section) -> DiscoveryResult:
    if section.error is not None:
        # No baseline from a failed query: the check skips the comparison then.
        yield Service()
        return
    if not section.services:
        return
    yield Service(
        parameters={
            "discovered_services": {
                s.name: {"account": s.account, "sid": s.sid}
                for s in section.services
                if classify(s.account, s.sid, section.computer, section.machine_sid)
                != "local_system"
            }
        }
    )


@dataclass
class _Account:
    name: str
    sid: str
    kind: str
    services: list[WinService]


def _group_accounts(section: Section, services: Iterable[WinService]) -> dict[str, _Account]:
    accounts: dict[str, _Account] = {}
    for service in services:
        key = account_key(service.account, service.sid)
        if key not in accounts:
            accounts[key] = _Account(
                name=service.account,
                sid=service.sid,
                kind=classify(service.account, service.sid, section.computer, section.machine_sid),
                services=[],
            )
        accounts[key].services.append(service)
    return accounts


def _account_details(account: _Account) -> str:
    head = f"{_display(account.name)} ({KIND_TITLES[account.kind]}"
    head += f", {account.sid})" if account.sid else ")"
    lines = [head] + [
        f"  {s.name} ({s.display_name}): {s.start_mode}, {s.state}"
        for s in sorted(account.services, key=lambda s: s.name.lower())
    ]
    return "\n".join(lines)


def _display(account: str) -> str:
    return account or "(no account)"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def check_service_accounts(params: Mapping[str, Any], section: Section) -> CheckResult:
    if section.error is not None:
        yield Result(
            state=State(params.get("query_error_state", 3)),
            summary=f"Agent plugin reported an error: {section.error}",
        )
        if not section.services:
            return

    builtin_kinds = set(params.get("builtin_kinds", DEFAULT_BUILTIN_KINDS))
    ignore_disabled = params.get("ignore_disabled", False)
    computer = section.computer

    def kind_of(account: str, sid: str) -> str:
        return classify(account, sid, computer, section.machine_sid)

    evaluated = [
        s for s in section.services if not (ignore_disabled and s.start_mode.lower() == "disabled")
    ]
    reported = [s for s in evaluated if kind_of(s.account, s.sid) not in builtin_kinds]
    accounts = _group_accounts(section, reported)

    yield Result(
        state=State.OK,
        summary=(
            f"{_plural(len(reported), 'service')} under "
            f"{_plural(len(accounts), 'service account')}"
        ),
    )
    yield Metric("service_account_services", len(reported))
    yield Metric("service_account_accounts", len(accounts))

    for account in sorted(accounts.values(), key=lambda a: a.name.lower()):
        yield Result(
            state=State.OK,
            notice=f"{_display(account.name)}: {_plural(len(account.services), 'service')}",
            details=_account_details(account),
        )


check_plugin_service_accounts = CheckPlugin(
    name="service_accounts",
    service_name="Service Accounts",
    discovery_function=discover_service_accounts,
    check_function=check_service_accounts,
    check_default_parameters={},
    check_ruleset_name="service_accounts",
)
```

How the output is built: the first result is the summary line. Each account then yields a result with `notice` and `details`. For an OK result Checkmk shows a notice only in the details of the service; for a result that is not OK the notice text is appended to the summary. That gives "one summary item per finding that changes the state" without extra code. `check_default_parameters={}` is required so that Checkmk passes `params` at all.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `41 passed`

- [ ] **Step 5: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Add discovery and summary check for service_accounts"
```

---

### Task 4: Allow list and unwanted accounts

**Files:**
- Modify: `plugins/service_accounts/agent_based/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: `check_service_accounts` from Task 3 with its local names `params`, `computer`, `accounts`, and the helpers `_display`, `_plural`, `_account_details`.
- Produces: `match_candidates(account, sid, computer) -> list[str]`, `compile_patterns(patterns, computer) -> tuple[list[re.Pattern[str]], list[str]]` (compiled, invalid), `matches_any(patterns, candidates) -> bool`. Inside `check_service_accounts`: the local function `is_allowed(account, sid) -> bool`, used by Task 5.
- Test helper produced: `_notices(params, section) -> dict[str, State]`.

Parameters handled here: `allowed` and `allowed_additional` (lists of regex strings, combined), `not_allowed_state` (int 0 to 3), `forbidden` (list of `{"pattern": str, "state": int}`, first match wins).

- [ ] **Step 1: Write the failing tests**

In `tests/test_service_accounts.py` add this helper after `_discovered`:

```python
def _notices(params, section) -> dict[str, State]:
    """Summary text -> state of all results that are not OK."""
    return {r.summary: r.state for r in _results(params, section) if r.state is not State.OK}
```

Append:

```python
# --- check: allow list and unwanted accounts --------------------------------


def test_check_account_without_name_is_reported_as_unknown() -> None:
    section = sa.parse_service_accounts(
        [
            ["computer", "SRV-APP01", MACHINE_SID],
            ["service", "A", "A", "", "", "Manual", "Stopped"],
        ]
    )
    results = _results({"not_allowed_state": 1}, section)
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
        "Invalid pattern in rule: 'CONTOSO\\\\\\\\(svc'": State.UNKNOWN,
        "Invalid pattern in rule: '['": State.UNKNOWN,
    }
```

Mind the escaping: in Python source `"CONTOSO\\\\svc_.*"` is the regex `CONTOSO\\svc_.*`, which matches the account `CONTOSO\svc_sql`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `9 failed, 41 passed in 0.37s` (assertion errors: all results are still OK)

- [ ] **Step 3: Implement the rule evaluation**

In `plugins/service_accounts/agent_based/service_accounts.py` add `import re` as the first import.

Add these functions above `def check_service_accounts`:

```python
def match_candidates(account: str, sid: str, computer: str) -> list[str]:
    """Strings a rule pattern is tried against."""
    candidates = [account]
    if sid:
        candidates.append(sid)
    if computer and account.startswith(".\\"):
        candidates.append(computer + account[1:])
    return candidates


def compile_patterns(
    patterns: Iterable[str], computer: str
) -> tuple[list[re.Pattern[str]], list[str]]:
    """Compile rule patterns, return (compiled, invalid).

    $HOSTNAME$ is replaced by the escaped computer name."""
    compiled, invalid = [], []
    for pattern in patterns:
        try:
            compiled.append(
                re.compile(pattern.replace("$HOSTNAME$", re.escape(computer)), re.IGNORECASE)
            )
        except re.error:
            invalid.append(pattern)
    return compiled, invalid


def matches_any(patterns: Iterable[re.Pattern[str]], candidates: Iterable[str]) -> bool:
    candidates = list(candidates)
    return any(p.fullmatch(c) for p in patterns for c in candidates)
```

In `check_service_accounts` replace the loop at the end of the function

```python
    for account in sorted(accounts.values(), key=lambda a: a.name.lower()):
        yield Result(
            state=State.OK,
            notice=f"{_display(account.name)}: {_plural(len(account.services), 'service')}",
            details=_account_details(account),
        )
```

with

```python
    allowed, invalid = compile_patterns(
        [*params.get("allowed", []), *params.get("allowed_additional", [])], computer
    )
    forbidden = []
    for entry in params.get("forbidden", []):
        compiled, bad = compile_patterns([entry["pattern"]], computer)
        invalid += bad
        forbidden += [(pattern, State(entry["state"])) for pattern in compiled]
    for pattern in invalid:
        yield Result(state=State.UNKNOWN, summary=f"Invalid pattern in rule: {pattern!r}")

    def is_allowed(account: str, sid: str) -> bool:
        return matches_any(allowed, match_candidates(account, sid, computer))

    not_allowed_state = params.get("not_allowed_state")
    for account in sorted(accounts.values(), key=lambda a: a.name.lower()):
        state = State.OK
        findings = []
        if not is_allowed(account.name, account.sid):
            candidates = match_candidates(account.name, account.sid, computer)
            for pattern, forbidden_state in forbidden:
                if matches_any([pattern], candidates):
                    state = forbidden_state
                    findings.append("unwanted account")
                    break
            if not_allowed_state is not None:
                state = State.worst(state, State(not_allowed_state))
                findings.append("not on the allow list")
        text = _plural(len(account.services), "service")
        yield Result(
            state=state,
            notice=(
                f"{_display(account.name)}: "
                + (f"{', '.join(findings)} ({text})" if findings else text)
            ),
            details=_account_details(account),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `50 passed`

- [ ] **Step 5: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Evaluate allow list and unwanted accounts"
```

---

### Task 5: Changes since the discovery

**Files:**
- Modify: `plugins/service_accounts/agent_based/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: in `check_service_accounts` the local names `params`, `section`, `evaluated` (services after `ignore_disabled`), `builtin_kinds`, `kind_of(account, sid)`, `is_allowed(account, sid)`; the discovered parameter `discovered_services` from Task 3; `_display`.
- Produces: `same_account(account_a, sid_a, account_b, sid_b) -> bool`, `_check_changes(changes, discovered, section, evaluated, is_relevant) -> CheckResult`.

Parameter handled here: `changes`, a dict with any of the keys `added`, `changed`, `removed` and a state (int 0 to 3) each. An account is relevant if its kind is not built-in and it is not on the allow list. A change is reported if the old or the new account is relevant.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_service_accounts.py`:

```python
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


def test_service_changed_from_local_system_counts_as_added(section) -> None:
    changed = _with("Spooler|Print Spooler|CONTOSO\\svc_x||Auto|Running")
    params = {"changes": CHANGES, **_discovered(section)}
    assert _notices(params, changed) == {"New service Spooler runs as CONTOSO\\svc_x": State.WARN}


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `6 failed, 57 passed in 0.37s`. The tests that expect no finding already pass; they guard against false positives once the comparison exists.

- [ ] **Step 3: Implement the change detection**

In `plugins/service_accounts/agent_based/service_accounts.py` add `Callable` to the import from `collections.abc`:

```python
from collections.abc import Callable, Iterable, Mapping, Sequence
```

Add these functions above `def check_service_accounts`:

```python
def same_account(account_a: str, sid_a: str, account_b: str, sid_b: str) -> bool:
    """Compare by SID only if both sides have one: a SID that could not be
    resolved this time (domain not reachable) must not look like a change."""
    if sid_a and sid_b:
        return sid_a.upper() == sid_b.upper()
    return account_a.lower() == account_b.lower()


def _check_changes(
    changes: Mapping[str, int],
    discovered: Mapping[str, Mapping[str, str]],
    section: Section,
    evaluated: Sequence[WinService],
    is_relevant: Callable[[str, str], bool],
) -> CheckResult:
    """Compare the services with the ones remembered by the service discovery."""
    for service in sorted(evaluated, key=lambda s: s.name.lower()):
        old = discovered.get(service.name)
        new_relevant = is_relevant(service.account, service.sid)
        if old is None:
            # Not in the baseline: the service is new or ran as LocalSystem.
            if new_relevant and "added" in changes:
                yield Result(
                    state=State(changes["added"]),
                    notice=f"New service {service.name} runs as {_display(service.account)}",
                )
            continue
        if same_account(old["account"], old["sid"], service.account, service.sid):
            continue
        if (new_relevant or is_relevant(old["account"], old["sid"])) and "changed" in changes:
            yield Result(
                state=State(changes["changed"]),
                notice=(
                    f"Account of service {service.name} changed from "
                    f"{_display(old['account'])} to {_display(service.account)}"
                ),
            )

    if "removed" not in changes:
        return
    existing = {s.name for s in section.services}
    for name, old in sorted(discovered.items()):
        if name not in existing and is_relevant(old["account"], old["sid"]):
            yield Result(
                state=State(changes["removed"]),
                notice=f"Service {name} ({_display(old['account'])}) no longer exists",
            )
```

Append to the end of `check_service_accounts` (same indentation as the account loop above it):

```python
    changes = params.get("changes")
    discovered = params.get("discovered_services")
    if changes and discovered is not None and section.error is None:
        yield from _check_changes(
            changes,
            discovered,
            section,
            evaluated,
            lambda account, sid: (
                kind_of(account, sid) not in builtin_kinds and not is_allowed(account, sid)
            ),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `63 passed`

- [ ] **Step 5: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Report service account changes since the discovery"
```

---

### Task 6: Inventory table and view

**Files:**
- Modify: `plugins/service_accounts/agent_based/service_accounts.py`
- Create: `plugins/service_accounts/inventory_ui/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: `Section`, `classify`, `DEFAULT_BUILTIN_KINDS`, `KIND_TITLES`.
- Produces: `inventory_service_accounts(section) -> InventoryResult`, `inventory_plugin_service_accounts`, `node_software_applications_service_accounts` with the view `invserviceaccounts`. Table path `["software", "applications", "service_accounts"]`, key column `service`, inventory columns `display_name`, `account`, `kind`, `start_mode`, status column `state`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_service_accounts.py` the imports now read:

```python
import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa
from cmk_addons.plugins.service_accounts.inventory_ui import service_accounts as inventory_ui
```

Append:

```python
# --- inventory --------------------------------------------------------------


def test_inventory_rows(section) -> None:
    rows = list(sa.inventory_service_accounts(section))
    assert [r.key_columns["service"] for r in rows] == [
        "MSSQLSERVER",
        "SQLAgent",
        "Backup",
        "WebApp",
        "Legacy",
    ]
    assert rows[2] == TableRow(
        path=["software", "applications", "service_accounts"],
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
    row = next(iter(sa.inventory_service_accounts(section)))
    node = inventory_ui.node_software_applications_service_accounts
    assert list(node.path) == row.path
    assert set(node.table.columns) == {
        *row.key_columns,
        *row.inventory_columns,
        *row.status_columns,
    }
    assert set(node.table.columns["kind"].mapping) == set(sa.KIND_TITLES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'cmk_addons.plugins.service_accounts.inventory_ui'`

- [ ] **Step 3: Implement the inventory plugin**

In `plugins/service_accounts/agent_based/service_accounts.py` the imports now read:

```python
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    InventoryPlugin,
    InventoryResult,
    Metric,
    Result,
    Service,
    State,
    StringTable,
    TableRow,
)
```

Append to the end of the file:

```python
def inventory_service_accounts(section: Section) -> InventoryResult:
    for service in section.services:
        kind = classify(service.account, service.sid, section.computer, section.machine_sid)
        if kind in DEFAULT_BUILTIN_KINDS:
            continue
        yield TableRow(
            path=["software", "applications", "service_accounts"],
            key_columns={"service": service.name},
            inventory_columns={
                "display_name": service.display_name,
                "account": service.account,
                "kind": kind,
                "start_mode": service.start_mode,
            },
            status_columns={"state": service.state},
        )


inventory_plugin_service_accounts = InventoryPlugin(
    name="service_accounts",
    inventory_function=inventory_service_accounts,
)
```

Inventory plugins get no check parameters, so the table always uses `DEFAULT_BUILTIN_KINDS`.

- [ ] **Step 4: Add titles and view**

Create `plugins/service_accounts/inventory_ui/service_accounts.py`:

```python
#!/usr/bin/env python3
"""Titles and view of the inventory table software > applications > service_accounts."""

from cmk.inventory_ui.v1_unstable import ChoiceField, Node, Table, TextField, Title, View

node_software_applications_service_accounts = Node(
    name="software_applications_service_accounts",
    path=["software", "applications", "service_accounts"],
    title=Title("Service accounts"),
    table=Table(
        view=View(name="invserviceaccounts", title=Title("Service accounts")),
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `65 passed`

- [ ] **Step 6: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Add inventory table and view for service accounts"
```

---

### Task 7: Check rule and graphing

**Files:**
- Create: `plugins/service_accounts/rulesets/service_accounts.py`
- Create: `plugins/service_accounts/graphing/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: the parameter names and value shapes the check reads (Tasks 3 to 5): `builtin_kinds: list[str]`, `ignore_disabled: bool`, `allowed: list[str]`, `allowed_additional: list[str]`, `not_allowed_state: int`, `forbidden: list[{"pattern": str, "state": int}]`, `changes: {"added"|"changed"|"removed": int}`, `query_error_state: int`; `DEFAULT_BUILTIN_KINDS`, `KIND_TITLES`; the metric names.
- Produces: `rule_spec_service_accounts` (`CheckParameters`, name `service_accounts`), `metric_service_account_services`, `metric_service_account_accounts`, `graph_service_accounts`, `perfometer_service_accounts`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_service_accounts.py` the imports now read:

```python
import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa
from cmk_addons.plugins.service_accounts.graphing import service_accounts as graphing
from cmk_addons.plugins.service_accounts.inventory_ui import service_accounts as inventory_ui
from cmk_addons.plugins.service_accounts.rulesets import service_accounts as rules
```

Append:

```python
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


def test_graphing_uses_the_metrics_of_the_check(section) -> None:
    yielded = {m.name for m in sa.check_service_accounts({}, section) if isinstance(m, Metric)}
    assert yielded == {
        graphing.metric_service_account_services.name,
        graphing.metric_service_account_accounts.name,
    }
    assert set(graphing.graph_service_accounts.simple_lines) == yielded
    assert set(graphing.perfometer_service_accounts.segments) <= yielded
```

Calling `parameter_form()` builds the whole form. That catches wrong form spec arguments, which `cmk-validate-plugins` does not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'cmk_addons.plugins.service_accounts.graphing'`

- [ ] **Step 3: Write the check rule**

Create `plugins/service_accounts/rulesets/service_accounts.py`:

```python
#!/usr/bin/env python3
"""Check parameters of the service "Service Accounts"."""

from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice,
    DefaultValue,
    DictElement,
    Dictionary,
    List,
    MatchingScope,
    MultipleChoice,
    MultipleChoiceElement,
    RegularExpression,
    ServiceState,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostCondition, Topic

_PATTERN_HELP = (
    "Regular expression that has to match the whole account, ignoring case. It is tried "
    "against the account name as configured in the service (e.g. <tt>CONTOSO\\svc_sql</tt>, "
    "<tt>svc_sql@contoso.example</tt>, <tt>.\\backup</tt>) and against its SID. A backslash "
    "has to be written as <tt>\\\\</tt>, e.g. <tt>CONTOSO\\\\svc_.*</tt>. "
    "<tt>$HOSTNAME$</tt> is replaced by the computer name of the host, so "
    "<tt>$HOSTNAME$\\\\backup</tt> matches the local user <tt>backup</tt> on every host, "
    "also if the service is configured with <tt>.\\backup</tt>."
)


def _pattern(title: Title) -> RegularExpression:
    return RegularExpression(
        title=title,
        help_text=Help(_PATTERN_HELP),
        predefined_help_text=MatchingScope.FULL,
    )


def _parameter_form() -> Dictionary:
    return Dictionary(
        help_text=Help(
            "Without a rule the service <i>Service Accounts</i> is always OK and only shows "
            "which Windows services run under a service account."
        ),
        elements={
            "builtin_kinds": DictElement(
                parameter_form=MultipleChoice(
                    title=Title("Built-in accounts"),
                    help_text=Help(
                        "Services running under these kinds of accounts are unremarkable and "
                        "not reported. Everything else counts as a service account."
                    ),
                    elements=[
                        MultipleChoiceElement(name="local_system", title=Title("Local System")),
                        MultipleChoiceElement(name="local_service", title=Title("Local Service")),
                        MultipleChoiceElement(
                            name="network_service", title=Title("Network Service")
                        ),
                        MultipleChoiceElement(
                            name="virtual", title=Title("Virtual accounts (NT SERVICE\\...)")
                        ),
                        MultipleChoiceElement(name="local_user", title=Title("Local users")),
                        MultipleChoiceElement(
                            name="managed",
                            title=Title("Managed service accounts (name ends with $)"),
                        ),
                        MultipleChoiceElement(name="domain", title=Title("Domain accounts")),
                        MultipleChoiceElement(name="unknown", title=Title("Unknown accounts")),
                    ],
                    prefill=DefaultValue(
                        ["local_system", "local_service", "network_service", "virtual"]
                    ),
                ),
            ),
            "ignore_disabled": DictElement(
                parameter_form=BooleanChoice(
                    title=Title("Disabled services"),
                    label=Label("Ignore services with the start mode Disabled"),
                    help_text=Help(
                        "By default disabled services are evaluated too, because Windows "
                        "keeps the credentials of their account."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
            "allowed": DictElement(
                parameter_form=List(
                    title=Title("Allowed accounts"),
                    help_text=Help(
                        "Accounts matching one of these patterns are always OK and exempt "
                        "from the other settings. In a more specific rule this list replaces "
                        "the list of a more general rule."
                    ),
                    element_template=_pattern(Title("Pattern")),
                    add_element_label=Label("Add pattern"),
                    editable_order=False,
                ),
            ),
            "allowed_additional": DictElement(
                parameter_form=List(
                    title=Title("Additional allowed accounts"),
                    help_text=Help(
                        "Like <i>Allowed accounts</i>, but in addition to the allow list of a "
                        "more general rule instead of replacing it. Use it for host specific "
                        "exceptions."
                    ),
                    element_template=_pattern(Title("Pattern")),
                    add_element_label=Label("Add pattern"),
                    editable_order=False,
                ),
            ),
            "not_allowed_state": DictElement(
                parameter_form=ServiceState(
                    title=Title("State for accounts that are not allowed"),
                    help_text=Help(
                        "State for every reported account that is not on the allow list. "
                        "Without this setting such accounts are only shown."
                    ),
                    prefill=DefaultValue(ServiceState.WARN),
                ),
            ),
            "forbidden": DictElement(
                parameter_form=List(
                    title=Title("Unwanted accounts"),
                    help_text=Help(
                        "Accounts that must not run services, e.g. personal or administrator "
                        "accounts. The first matching entry determines the state. Accounts on "
                        "the allow list are not checked."
                    ),
                    element_template=Dictionary(
                        elements={
                            "pattern": DictElement(
                                required=True, parameter_form=_pattern(Title("Pattern"))
                            ),
                            "state": DictElement(
                                required=True,
                                parameter_form=ServiceState(
                                    title=Title("State"),
                                    prefill=DefaultValue(ServiceState.CRIT),
                                ),
                            ),
                        },
                    ),
                    add_element_label=Label("Add account"),
                ),
            ),
            "changes": DictElement(
                parameter_form=Dictionary(
                    title=Title("Changes since the service discovery"),
                    help_text=Help(
                        "The service discovery remembers which service runs under which "
                        "account. Report differences to that for services running under a "
                        "reported account that is not on the allow list. To accept a change, "
                        "update the service parameters in the service discovery of the host."
                    ),
                    elements={
                        "added": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if a service was added"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                        "changed": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if the account of a service changed"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                        "removed": DictElement(
                            parameter_form=ServiceState(
                                title=Title("State if a service was removed"),
                                prefill=DefaultValue(ServiceState.WARN),
                            ),
                        ),
                    },
                ),
            ),
            "query_error_state": DictElement(
                parameter_form=ServiceState(
                    title=Title("State if the agent plugin reported an error"),
                    prefill=DefaultValue(ServiceState.UNKNOWN),
                ),
            ),
        },
    )


rule_spec_service_accounts = CheckParameters(
    name="service_accounts",
    title=Title("Service accounts (Windows)"),
    topic=Topic.OPERATING_SYSTEM,
    parameter_form=_parameter_form,
    condition=HostCondition(),
)
```

Every element is optional, so a rule sets only what it should override. Checkmk merges matching rules key by key: that is why `allowed` in a more specific rule replaces the general list while `allowed_additional` adds to it.

- [ ] **Step 4: Write the graphing definitions**

Create `plugins/service_accounts/graphing/service_accounts.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `67 passed`

- [ ] **Step 6: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Add check rule and graphing for service accounts"
```

---

### Task 8: Agent plugin and bakery

**Files:**
- Create: `plugins/service_accounts/agents/service_accounts.ps1`
- Create: `plugins/service_accounts/rulesets/agent_config.py`
- Create: `plugins/service_accounts/bakery/service_accounts.py`
- Modify: `tests/test_service_accounts.py`

**Interfaces:**
- Consumes: the section format parsed in Task 1.
- Produces: `rule_spec_service_accounts_bakery` (`AgentConfig`, name `service_accounts`) with the value shape `{"deployment": ("deploy" | "do_not_deploy", None), "interval": float}` (`interval` optional, seconds); `bakery_plugin_service_accounts` (name `service_accounts`), `get_service_accounts_files(conf) -> FileGenerator`.

The PowerShell script cannot run in the devcontainer (no `pwsh`). The tests only check that the file exists where the bakery looks for it, that it is ASCII and that it prints the section header. The user verifies the script on Windows hosts (Task 9, Step 8).

- [ ] **Step 1: Write the failing tests**

In `tests/test_service_accounts.py` the imports now read:

```python
from pathlib import Path

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State, TableRow
from cmk_addons.plugins.service_accounts.agent_based import service_accounts as sa
from cmk_addons.plugins.service_accounts.bakery import service_accounts as bakery
from cmk_addons.plugins.service_accounts.graphing import service_accounts as graphing
from cmk_addons.plugins.service_accounts.inventory_ui import service_accounts as inventory_ui
from cmk_addons.plugins.service_accounts.rulesets import agent_config
from cmk_addons.plugins.service_accounts.rulesets import service_accounts as rules
```

Append:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_accounts.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'cmk_addons.plugins.service_accounts.bakery'`

- [ ] **Step 3: Write the agent plugin**

Create `plugins/service_accounts/agents/service_accounts.ps1`:

```powershell
<#
.SYNOPSIS
    Checkmk agent plugin: Windows services and the accounts they run under.
.DESCRIPTION
    Prints every service, unfiltered. The evaluation (which accounts count as
    service accounts, which are allowed) happens on the Checkmk server in the
    check plugin service_accounts, so the plugin needs no configuration.

    <<<service_accounts:sep(124)>>>
    computer|<computer name>|<machine SID>
    service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
    error|<message>

    Keep this file ASCII only: Windows PowerShell 5.1 reads scripts without a
    BOM in the ANSI code page.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:SidCache = @{}

function Format-Field {
    # Pipes and line breaks would break the section format.
    param($Value)
    if ($null -eq $Value) { return '' }
    return (([string]$Value) -replace '[|\r\n]+', ' ').Trim()
}

function Get-MachineSid {
    # The SID prefix shared by the local accounts of this computer.
    try {
        $account = Get-CimInstance -ClassName Win32_UserAccount -Filter 'LocalAccount=True' |
            Select-Object -First 1
        if ($account) {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($account.SID)
            return $sid.AccountDomainSid.Value
        }
    } catch {
        # Leave the field empty: the check then falls back to the account name.
    }
    return ''
}

function Get-AccountSid {
    # Empty if the account cannot be translated (deleted, domain not reachable).
    param([string]$Account)
    if ([string]::IsNullOrEmpty($Account)) { return '' }
    $key = $Account.ToLowerInvariant()
    if ($script:SidCache.ContainsKey($key)) { return $script:SidCache[$key] }

    $sid = ''
    if ($key -eq 'localsystem' -or $key -eq '.\localsystem') {
        # Not an account name the LSA can translate.
        $sid = 'S-1-5-18'
    } else {
        $name = $Account
        if ($name.StartsWith('.\')) { $name = $env:COMPUTERNAME + $name.Substring(1) }
        try {
            $ntAccount = New-Object System.Security.Principal.NTAccount($name)
            $sid = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
        } catch {
            $sid = ''
        }
    }
    $script:SidCache[$key] = $sid
    return $sid
}

Write-Host '<<<service_accounts:sep(124)>>>'
Write-Host ('computer|{0}|{1}' -f (Format-Field $env:COMPUTERNAME), (Get-MachineSid))

try {
    $services = Get-CimInstance -ClassName Win32_Service `
        -Property Name, DisplayName, StartName, StartMode, State | Sort-Object -Property Name
    foreach ($service in $services) {
        $fields = @(
            'service',
            (Format-Field $service.Name),
            (Format-Field $service.DisplayName),
            (Format-Field $service.StartName),
            (Get-AccountSid (Format-Field $service.StartName)),
            (Format-Field $service.StartMode),
            (Format-Field $service.State)
        )
        Write-Host ($fields -join '|')
    }
} catch {
    Write-Host ('error|' + (Format-Field $_.Exception.Message))
}
```

Notes for the implementer: `LocalSystem` is not a name the LSA translates, hence the fixed SID. `.\name` is translated as `<COMPUTERNAME>\name`. The cache avoids translating the same account for every service, which matters when a domain is not reachable and each lookup runs into a timeout. `$ErrorActionPreference = 'Stop'` turns a failing `Get-CimInstance` into an exception, which becomes the `error` line.

- [ ] **Step 4: Write the bakery rule**

Create `plugins/service_accounts/rulesets/agent_config.py`:

```python
#!/usr/bin/env python3
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
```

- [ ] **Step 5: Write the bakery plugin**

Create `plugins/service_accounts/bakery/service_accounts.py`:

```python
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
```

`default_parameters=None` means: without a rule the plugin is not deployed. An interval makes the Windows agent run the plugin asynchronously and cache the output.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_service_accounts.py -q`
Expected: `50 passed`

- [ ] **Step 7: Lint and commit**

```bash
black plugins/ tests/ && isort plugins/ tests/ && flake8 plugins/ tests/
git add plugins/service_accounts tests
git commit -m "Add agent plugin and bakery integration for service accounts"
```

---

### Task 9: Man page, docs and verification in the dev site

**Files:**
- Create: `plugins/service_accounts/checkman/service_accounts`
- Modify: `Changelog.md`
- Modify: `docs/superpowers/specs/2026-10-13-service-accounts-design.md` (append)
- Modify: `CLAUDE.local.md` (not tracked)
- Create: `temp/service_accounts_agent.txt` (not tracked)

**Interfaces:**
- Consumes: everything from Tasks 1 to 8.
- Produces: nothing other tasks use.

If a step in the dev site fails, stop and find the cause (use superpowers:systematic-debugging); do not adjust the expected output to match.

- [ ] **Step 1: Write the man page**

Create `plugins/service_accounts/checkman/service_accounts` (no file extension; every description line starts with a blank):

```text
title: Windows: Service Accounts
agents: windows
catalog: os/services
license: GPLv2
distribution: chexma
description:
 This check shows which Windows services do not run under a built-in system
 account but under a service account: a domain account, a local user or a
 managed service account. It needs the agent plugin {service_accounts.ps1},
 which is deployed with the agent bakery rule {Service accounts (Windows)}.

 Every account gets a kind, by its SID if the agent could translate the
 account, otherwise by its name: Local System, Local Service, Network
 Service, virtual account ({NT SERVICE\...}), local user, managed service
 account (name ends with {$}), domain account or unknown. By default the
 first four kinds are built-in accounts and not reported.

 Without a rule the service is always {OK}. With the rule
 {Service accounts (Windows)} for the service you can set which kinds are
 built-in accounts, ignore disabled services, define an allow list and a
 state for accounts that are not on it, define unwanted accounts with a
 state, and report changes since the service discovery: added services,
 changed accounts and removed services. To accept a change, update the
 service parameters in the service discovery of the host. If the agent
 plugin reports an error the service is {UNKNOWN} (configurable).

 Patterns are regular expressions that have to match the whole account
 name or SID, ignoring case. {$HOSTNAME$} is replaced by the computer name.

 Limitations: computer accounts ({DOMAIN\HOST$}) are shown as managed
 service accounts. On a domain controller the local accounts are the domain
 accounts, so domain accounts are shown as local users there. An account in
 UPN notation that cannot be translated to a SID is shown as domain account.

 The services are also available in the HW/SW inventory under
 {Software > Applications > Service accounts}.

discovery:
 One service is created for each host whose agent sends the section
 {service_accounts} with at least one service or an error.
```

- [ ] **Step 2: Validate the plugins and reload the site**

```bash
cmk-validate-plugins
cmk -R
omd restart apache
```

Expected: `cmk-validate-plugins` reports no error for `service_accounts`.

Then check that both rulesets exist:

```bash
API=http://localhost:5000/cmk/check_mk/api/1.0
AUTH="Authorization: Bearer cmkadmin cmkadmin"
for r in checkgroup_parameters:service_accounts agent_config:service_accounts; do
    curl -sS -o /dev/null -w "$r %{http_code}\n" -H "$AUTH" "$API/objects/ruleset/$r"
done
```

Expected: `200` for both.

- [ ] **Step 3: Create a test host with canned agent output**

```bash
mkdir -p temp
cat > temp/service_accounts_agent.txt <<'EOF'
<<<check_mk>>>
Version: 2.5.0p15
AgentOS: windows
<<<service_accounts:sep(124)>>>
computer|SRV-APP01|S-1-5-21-1000-2000-3000
service|Spooler|Print Spooler|LocalSystem|S-1-5-18|Auto|Running
service|Dhcp|DHCP Client|NT AUTHORITY\LocalService|S-1-5-19|Auto|Running
service|Dnscache|DNS Client|NT-AUTORITÄT\Netzwerkdienst|S-1-5-20|Auto|Running
service|MSSQL$X|SQL Server (X)|NT SERVICE\MSSQL$X|S-1-5-80-1-2-3-4-5|Auto|Running
service|MSSQLSERVER|SQL Server|CONTOSO\svc_sql|S-1-5-21-4000-5000-6000-1105|Auto|Running
service|SQLAgent|SQL Server Agent|CONTOSO\svc_sql|S-1-5-21-4000-5000-6000-1105|Manual|Stopped
service|Backup|Backup Service|.\backup|S-1-5-21-1000-2000-3000-1001|Disabled|Stopped
service|WebApp|Web App|CONTOSO\gmsa_web$|S-1-5-21-4000-5000-6000-1106|Auto|Running
service|Legacy|Legacy App|CONTOSO\old_admin||Auto|Stopped
EOF
.devcontainer/test-host.sh srv-app01 temp/service_accounts_agent.txt
cmk -vI --detect-plugins=service_accounts srv-app01
cmk -v --detect-plugins=service_accounts srv-app01
```

Expected: the discovery finds one `service_accounts` service. The check prints `Service Accounts` with `5 services under 4 service accounts`, state OK.

- [ ] **Step 4: Check the rule evaluation and the discovered baseline**

Create a check rule (the value is a Python literal; `r"CONTOSO\\svc_.*"` is the regex `CONTOSO\\svc_.*`):

```bash
VALUE=$(python3 -c 'print(repr({"not_allowed_state": 1, "allowed": [r"CONTOSO\\svc_.*"], "changes": {"added": 1, "changed": 2, "removed": 1}}))')
curl -sS -X POST -H "$AUTH" -H "Content-Type: application/json" -H "Accept: application/json" \
    "$API/domain-types/rule/collections/all" \
    -d "$(jq -n --arg v "$VALUE" '{ruleset: "checkgroup_parameters:service_accounts", folder: "/", properties: {description: "service_accounts dev test"}, value_raw: $v, conditions: {}}')" |
    jq -r '.id // .'
cmk -v --detect-plugins=service_accounts srv-app01
```

Expected: the API returns a rule id (an error here means the form rejects the value: fix the form, not the value). The check is WARN and names `.\backup`, `CONTOSO\gmsa_web$` and `CONTOSO\old_admin` as `not on the allow list`; `CONTOSO\svc_sql` is not named.

Now change the canned data and check again without a new discovery:

```bash
sed -i 's/^service|Legacy|Legacy App|CONTOSO\\old_admin|/service|Legacy|Legacy App|CONTOSO\\other_admin|/' temp/service_accounts_agent.txt
printf '%s\n' 'service|NewApp|New App|CONTOSO\new_admin||Auto|Running' >> temp/service_accounts_agent.txt
cmk -v --detect-plugins=service_accounts srv-app01
```

Expected: CRIT, with `Account of service Legacy changed from CONTOSO\old_admin to CONTOSO\other_admin` and `New service NewApp runs as CONTOSO\new_admin`. This proves that the discovered parameters survive being stored in the autochecks file.

Accept the changes and check once more:

```bash
cmk -vII --detect-plugins=service_accounts srv-app01
cmk -v --detect-plugins=service_accounts srv-app01
```

Expected: WARN again, only the `not on the allow list` findings, no change findings.

- [ ] **Step 5: Check the inventory**

```bash
cmk -vi srv-app01
```

Expected: no traceback. The tree is only stored by the inventory service, and the factory rules enable that only for hosts with special labels. Enable it for all hosts, activate (running `test-host.sh` again activates the changes) and trigger the service:

```bash
curl -sS -X POST -H "$AUTH" -H "Content-Type: application/json" -H "Accept: application/json" \
    "$API/domain-types/rule/collections/all" \
    -d "$(jq -n '{ruleset: "active_checks:cmk_inv", folder: "/", properties: {description: "service_accounts dev test"}, value_raw: "{\"status_data_inventory\": True}", conditions: {}}')" |
    jq -r '.id // .'
.devcontainer/test-host.sh srv-app01 temp/service_accounts_agent.txt
NOW=$(date +%s)
echo "COMMAND [$NOW] SCHEDULE_FORCED_SVC_CHECK;srv-app01;Check_MK HW/SW Inventory;$NOW" | lq
sleep 30
grep -rl service_accounts ~/var/check_mk/inventory/ 2>/dev/null
```

Expected: a file for `srv-app01` is listed. If nothing is listed, look at the state of the service `Check_MK HW/SW Inventory` of `srv-app01` in the GUI before changing code.

- [ ] **Step 6: Bake an agent**

```bash
VALUE=$(python3 -c 'print(repr({"deployment": ("deploy", None), "interval": 3600.0}))')
curl -sS -X POST -H "$AUTH" -H "Content-Type: application/json" -H "Accept: application/json" \
    "$API/domain-types/rule/collections/all" \
    -d "$(jq -n --arg v "$VALUE" '{ruleset: "agent_config:service_accounts", folder: "/", properties: {description: "service_accounts dev test"}, value_raw: $v, conditions: {}}')" |
    jq -r '.id // .'
cmk -v -A srv-app01
```

Expected: the API returns a rule id and the bake finishes without a traceback. If baking the Windows MSI fails for a reason unrelated to this plugin (e.g. a missing agent signature key), report the exact output to the user instead of working around it; the user then bakes in the GUI.

- [ ] **Step 7: Run everything CI runs**

Run: `.devcontainer/ci.sh`
Expected: black, isort and flake8 without findings, `50 passed`, `cmk-validate-plugins` without errors.

- [ ] **Step 8: Update the docs**

In `Changelog.md` add below `## [Unreleased]`:

```markdown
- Initial implementation: agent plugin `service_accounts.ps1` with bakery
  rule, service `Service Accounts` with check parameters, metrics and graph,
  HW/SW inventory table with view.
```

Append to `docs/superpowers/specs/2026-10-13-service-accounts-design.md`:

```markdown
## Amendments from the implementation

- `discovered_services` maps a service name to `{"account": <name>,
  "sid": <SID or "">}`. Accounts are compared by SID if both sides have one,
  otherwise by name ignoring case, so a SID that cannot be translated on one
  agent run is not a change.
- A pattern is also tried against `<computer name>\name` if the service is
  configured with `.\name`.
- An invalid pattern yields an UNKNOWN result naming the pattern.
- With `ignore_disabled`, disabled services are also left out of the change
  detection.
- A discovery during a plugin error stores no baseline; without a baseline
  and during a plugin error there is no change detection.
- Limitations: computer accounts (`DOMAIN\HOST$`) are classified as
  `managed`; on a domain controller domain accounts are classified as
  `local_user`; a UPN without SID is classified as `domain`.
```

In `CLAUDE.local.md` replace the `Status (2026-10-13): ...` paragraph, up to and including the `Next step:` sentence, with:

```markdown
Status (2026-10-13): implemented following
`docs/superpowers/plans/2026-10-13-service-accounts.md`, tests and dev-site
checks pass. Not yet done: verification of `service_accounts.ps1` on real
Windows hosts (see Open points), `package` manifest and MKP.
```

- [ ] **Step 9: Commit**

```bash
git add plugins/service_accounts Changelog.md docs/superpowers
git commit -m "Add man page, changelog and spec amendments for service_accounts"
```

- [ ] **Step 10: Hand over the Windows verification to the user**

The script cannot be tested here. Tell the user to run `service_accounts.ps1` on these hosts and to send back the output with all names replaced by fictional ones:

1. English Windows, domain member: `<account SID>` is filled for domain accounts, `S-1-5-18` for `LocalSystem`, `S-1-5-80-...` for `NT SERVICE\...`; the machine SID in the `computer` line is the prefix of the SIDs of local users.
2. German Windows: the same, and umlauts in display names arrive intact in Checkmk (`cmk -d <host>`).
3. A service whose account was deleted: the line has an empty SID field and the script does not abort.
4. A domain controller: note what the `computer` line contains (the known limitation from the man page).
5. Run time with the domain not reachable, to judge whether the cache interval of the bakery rule should be recommended as default.

The dev-site rules with the description `service_accounts dev test` and the host `srv-app01` stay for further tests; remove the host with `.devcontainer/test-host.sh --remove srv-app01` when done.
