#!/usr/bin/env python3
# Copyright (C) 2026 chexma - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
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
    # Further spellings of the same account (same SID), e.g. UPN and DOMAIN\name
    other_names: list[str]

    @property
    def names(self) -> list[str]:
        return [self.name, *self.other_names]


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
                other_names=[],
            )
        account = accounts[key]
        account.services.append(service)
        if service.account.lower() not in (name.lower() for name in account.names):
            account.other_names.append(service.account)
    return accounts


def _account_details(
    account: _Account, findings: Sequence[str] = (), affected: Iterable[WinService] = ()
) -> str:
    """One line per service of the account, the findings behind the affected ones."""
    suffix = f": {', '.join(findings)}" if findings else ""
    affected_names = {s.name for s in affected}
    return "\n".join(
        f"{s.name}{f' ({s.display_name})' if s.display_name else ''}: "
        f"{_display(s.account)} ({KIND_TITLES[account.kind]}), {s.start_mode}, {s.state}"
        + (suffix if s.name in affected_names else "")
        for s in sorted(account.services, key=lambda s: s.name.lower())
    )


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


# Findings named in the summary; further ones are counted there and listed in the details.
SUMMARY_LIMIT = 10

_STATE_MARKERS = {State.OK: "", State.WARN: "(!)", State.CRIT: "(!!)", State.UNKNOWN: "(?)"}
_SEVERITY = {State.CRIT: 0, State.UNKNOWN: 1, State.WARN: 2, State.OK: 3}

# state, text for the summary, text for the details
_Finding = tuple[State, str, str]


def _baseline(params: Mapping[str, Any]) -> dict[str, dict[str, str]] | None:
    """The services remembered by the service discovery, None if there are none."""
    raw = params.get("discovered_services")
    if not isinstance(raw, Mapping):
        return None
    return {
        str(name): {"account": str(old.get("account", "")), "sid": str(old.get("sid", ""))}
        for name, old in raw.items()
        if isinstance(old, Mapping)
    }


def _changes(
    changes: Mapping[str, int],
    discovered: Mapping[str, Mapping[str, str]],
    section: Section,
    evaluated: Sequence[WinService],
    is_relevant: Callable[[str, str, str], bool],
) -> Iterable[_Finding]:
    """Compare the services with the ones remembered by the service discovery."""
    for service in sorted(evaluated, key=lambda s: s.name.lower()):
        if not (service.account or service.sid):
            # Not part of the baseline, see discover_service_accounts.
            continue
        old = discovered.get(service.name)
        new_relevant = is_relevant(service.name, service.account, service.sid)
        if old is None:
            if new_relevant and "added" in changes:
                text = f"New service {service.name} runs as {_display(service.account)}"
                yield State(changes["added"]), text, text
            continue
        if same_account(old["account"], old["sid"], service.account, service.sid):
            continue
        old_relevant = is_relevant(service.name, old["account"], old["sid"])
        if (new_relevant or old_relevant) and "changed" in changes:
            old_name, new_name = _display(old["account"]), _display(service.account)
            if old_name.lower() == new_name.lower():
                # The account was deleted and created again: only the SID tells.
                old_name += f" ({old['sid']})"
                new_name += f" ({service.sid})"
            text = f"Account of service {service.name} changed from {old_name} to {new_name}"
            yield State(changes["changed"]), text, text

    if "removed" not in changes:
        return
    existing = {s.name for s in section.services}
    for name, old in sorted(discovered.items()):
        if name not in existing and is_relevant(name, old["account"], old["sid"]):
            text = f"Service {name} ({_display(old['account'])}) no longer exists"
            yield State(changes["removed"]), text, text


def _report(findings: Iterable[_Finding]) -> CheckResult:
    """The worst findings go to the summary, the others are counted there."""
    ordered = sorted(findings, key=lambda finding: _SEVERITY[finding[0]])
    not_ok = [finding for finding in ordered if finding[0] is not State.OK]
    for state, text, details in not_ok[:SUMMARY_LIMIT]:
        yield Result(state=state, notice=text, details=details)
    if rest := not_ok[SUMMARY_LIMIT:]:
        yield Result(
            state=State.worst(*(state for state, _text, _details in rest)),
            summary=f"{_plural(len(rest), 'more finding')} (see details)",
            details="\n".join(
                line + _STATE_MARKERS[state]
                for state, _text, details in rest
                for line in details.splitlines()
            ),
        )
    for state, text, details in ordered[len(not_ok) :]:
        yield Result(state=state, notice=text, details=details)


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
    discovered = _baseline(params)
    # If the agent could not translate an account this time (domain not
    # reachable), patterns written against the SID still have to match.
    known_sids = {
        old["account"].lower(): old["sid"] for old in (discovered or {}).values() if old["sid"]
    }

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

    invalid: list[str] = []

    def compiled(pattern: str) -> list[re.Pattern[str]]:
        patterns, bad = compile_patterns([pattern], computer)
        invalid.extend(bad)
        return patterns

    # (service pattern or None for every service, account pattern)
    allowed: list[tuple[re.Pattern[str] | None, re.Pattern[str]]] = []
    for entry in [*params.get("allowed", []), *params.get("allowed_additional", [])]:
        if isinstance(entry, str):
            # Rules saved before 2.5.3 hold plain account patterns.
            entry = {"account": entry}
        service_patterns = compiled(entry["service"]) if entry.get("service") else [None]
        allowed += [(sp, ap) for sp in service_patterns for ap in compiled(entry["account"])]
    forbidden = [
        (pattern, State(entry["state"]))
        for entry in params.get("forbidden", [])
        for pattern in compiled(entry["pattern"])
    ]
    for pattern in invalid:
        yield Result(state=State.UNKNOWN, summary=f"Invalid pattern in rule: {pattern}")

    def candidates_of(names: Sequence[str], sid: str) -> list[str]:
        sid = sid or next(
            (known_sids[name.lower()] for name in names if name.lower() in known_sids), ""
        )
        return [c for name in names for c in match_candidates(name, sid, computer)]

    def is_allowed(service_name: str, candidates: Sequence[str]) -> bool:
        return any(
            (service_pattern is None or service_pattern.fullmatch(service_name))
            and matches_any([account_pattern], candidates)
            for service_pattern, account_pattern in allowed
        )

    findings: list[_Finding] = []
    not_allowed_state = params.get("not_allowed_state")
    for account in sorted(accounts.values(), key=lambda a: a.name.lower()):
        state = State.OK
        reasons = []
        candidates = candidates_of(account.names, account.sid)
        denied = [s for s in account.services if not is_allowed(s.name, candidates)]
        if denied:
            for pattern, forbidden_state in forbidden:
                if matches_any([pattern], candidates):
                    state = forbidden_state
                    reasons.append("unwanted account")
                    break
            if not_allowed_state is not None:
                state = State.worst(state, State(not_allowed_state))
                reasons.append("not on the allow list")
        text = _plural(len(account.services), "service")
        if reasons and len(denied) < len(account.services):
            text = f"{len(denied)} of {text}"
        findings.append(
            (
                state,
                f"{_display(account.name)}: "
                + (f"{', '.join(reasons)} ({text})" if reasons else text),
                _account_details(account, reasons, denied),
            )
        )

    changes = params.get("changes")
    if changes and section.error is None:
        if discovered is None:
            yield Result(
                state=State.OK,
                summary="No change detection: no baseline, run the service discovery",
            )
        else:
            findings += _changes(
                changes,
                discovered,
                section,
                evaluated,
                lambda service_name, account, sid: (
                    kind_of(account, sid) not in builtin_kinds
                    and not is_allowed(service_name, candidates_of([account], sid))
                ),
            )
    yield from _report(findings)


check_plugin_service_accounts = CheckPlugin(
    name="service_accounts",
    service_name="Service Accounts",
    discovery_function=discover_service_accounts,
    check_function=check_service_accounts,
    # Service accounts have to be allowed explicitly; a rule can set the state to OK.
    check_default_parameters={"not_allowed_state": 1},
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
