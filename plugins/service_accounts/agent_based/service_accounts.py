#!/usr/bin/env python3
"""Windows services and the accounts they run under.

Section <<<service_accounts:sep(124)>>> (agent plugin service_accounts.ps1):

    computer|<computer name>|<machine SID>
    service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
    error|<message>
"""

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


DEFAULT_BUILTIN_KINDS = (
    "local_system",
    "local_service",
    "network_service",
    "virtual",
    "no_account",
)


KIND_TITLES = {
    "local_system": "Local System",
    "local_service": "Local Service",
    "network_service": "Network Service",
    "virtual": "virtual account",
    "no_account": "no account",
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
    if not name:
        # E.g. per-user service instances, whose names change with every logon.
        return "no_account"
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
                # Without an account: names change with every logon, no baseline.
                if s.account or s.sid
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
        if not (service.account or service.sid):
            # Not part of the baseline, see discover_service_accounts.
            continue
        old = discovered.get(service.name)
        new_relevant = is_relevant(service.account, service.sid)
        if old is None:
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


check_plugin_service_accounts = CheckPlugin(
    name="service_accounts",
    service_name="Service Accounts",
    discovery_function=discover_service_accounts,
    check_function=check_service_accounts,
    check_default_parameters={},
    check_ruleset_name="service_accounts",
)


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
