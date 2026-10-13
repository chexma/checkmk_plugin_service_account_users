# Design: Checkmk plugin `service_accounts`

Date: 2026-10-13. Status: design agreed with the user, nothing implemented yet.

## Purpose

Show which Windows services do not run under a built-in system account but
under a service account (domain account, local user, gMSA), and optionally
alert on accounts that are not allowed. Deployment and configuration of the
agent plugin go through the agent bakery.

Target: Checkmk 2.5 (devcontainer: `ultimate` 2.5.0p15). Windows hosts only.
Model for structure and conventions: the plugin `local_group_members`.

## Data flow

Bakery rule -> `service_accounts.ps1` on the host -> section
`<<<service_accounts:sep(124)>>>` -> one service `Service Accounts` per host,
plus the inventory table `software > applications > service_accounts`.

## Components

All files live in `plugins/service_accounts/`.

| Component | File |
|---|---|
| Agent plugin (PowerShell) | `agents/service_accounts.ps1` |
| Section, check and inventory plugin | `agent_based/service_accounts.py` |
| Check parameters | `rulesets/service_accounts.py` |
| Bakery ruleset | `rulesets/agent_config.py` |
| Bakery plugin (`cmk.bakery.v2_unstable`) | `bakery/service_accounts.py` |
| Metrics, graph, perfometer | `graphing/service_accounts.py` |
| Inventory table titles and view | `inventory_ui/service_accounts.py` |
| Checkman | `checkman/service_accounts` |
| Tests | `tests/test_service_accounts.py` |

The bakery (API v2) takes the plugin source from the family's `agents/`
directory, not from `agents/windows/plugins/`.

## Agent plugin

`service_accounts.ps1` reads all services with
`Get-CimInstance Win32_Service` and prints one line per service. It does not
filter: services running as LocalSystem are reported too. All evaluation
happens in the check, so changing a rule never requires baking agents.

The plugin has no configuration file.

Section format, fields separated by pipes:

```text
<<<service_accounts:sep(124)>>>
computer|<computer name>|<machine SID>
service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
```

- `<account>` is `StartName` as configured (e.g. `LocalSystem`,
  `NT AUTHORITY\NetworkService`, `CONTOSO\svc_sql`, `.\backup`,
  `svc_sql@contoso.example`). Empty if the service has none.
- `<account SID>` is the account translated to a SID, empty if the
  translation fails (e.g. deleted account, domain not reachable). The SID
  makes the classification independent of the OS language.
- `<machine SID>` is the SID prefix shared by the local accounts of the
  computer; it distinguishes local users from domain accounts. Empty if it
  cannot be determined.
- `<start mode>` and `<state>` are the `StartMode` and `State` values of
  `Win32_Service` (`Auto`, `Manual`, `Disabled`, ...; `Running`, `Stopped`, ...).
- Pipes and line breaks inside a field are replaced by a blank.
- The output is UTF-8.

An error while reading the services yields the header and the `computer`
line followed by `error|<message>`.

## Bakery

Rule "Service accounts (Windows)", topic operating system:

- Deployment: deploy the plugin / do not deploy the plugin.
- Optional: run asynchronously and cache the result (default 1 hour).

The bakery plugin yields one `Plugin` for `OS.WINDOWS` with the interval.
What counts as a service account is not a bakery setting.

## Check `Service Accounts`

One service per host, discovered if the section contains at least one
`service` line or an `error` line.

### Account kinds

Every account gets a kind, by SID if there is one, otherwise by name:

| Kind | By SID | By name (fallback) |
|---|---|---|
| `local_system` | `S-1-5-18` | `LocalSystem`, `.\LocalSystem`, `NT AUTHORITY\SYSTEM` |
| `local_service` | `S-1-5-19` | `NT AUTHORITY\LocalService` |
| `network_service` | `S-1-5-20` | `NT AUTHORITY\NetworkService` |
| `virtual` | `S-1-5-80-*` | `NT SERVICE\*` |
| `local_user` | `S-1-5-21-*` with the machine SID as prefix | `.\name`, `<computer name>\name` |
| `managed` | domain SID, name ends with `$` | `DOMAIN\name$` |
| `domain` | any other `S-1-5-21-*` | `DOMAIN\name`, `name@domain` |
| `unknown` | anything else | anything else, also an empty account |

Name comparisons ignore case.

### Parameters

Without a rule the service is always OK and only displays.

| Parameter | Effect | Default |
|---|---|---|
| `builtin_kinds` | Kinds that are unremarkable; services under them are not reported | `local_system`, `local_service`, `network_service`, `virtual` |
| `ignore_disabled` | Do not evaluate services with start mode `Disabled` | off (credentials are stored for disabled services too) |
| `allowed` | Allow list: regexes for accounts that are always OK and exempt from the other settings | empty |
| `allowed_additional` | Added to the allow list of a more general rule instead of replacing it | empty |
| `not_allowed_state` | State for every reported account that is not on the allow list | not set |
| `forbidden` | Unwanted accounts: list of regex + state; the first matching entry determines the state | empty |
| `changes` | States for changes since the service discovery: `added`, `changed`, `removed` | not set |
| `query_error_state` | State if the plugin reported an error | UNKNOWN |

Regexes are full-match, case-insensitive, and are tried against the account
name and the SID. `$HOSTNAME$` in a pattern is replaced by the computer name
from the `computer` line (escaped).

### Changes since the discovery

The discovery stores `discovered_services` in the discovered parameters: a
mapping service name -> account (SID if known, else name) for every service
that does not run as `local_system`. The check compares it with the current
data, limited to services whose old or new account is reported under the
current rule:

- `added`: a service runs under a reported account and was not in the mapping.
- `changed`: the account of a service differs from the mapping.
- `removed`: a service from the mapping no longer exists.

Accounts on the allow list may be added without notice. A change is accepted
by updating the service parameters in the service discovery of the host.

### Output

- Summary: `5 services under 3 service accounts`, plus one summary item per
  finding that changes the state.
- Details: one block per account with its kind and its services (name,
  display name, start mode, state).
- Metrics, without levels: `service_account_services` (services under
  reported accounts) and `service_account_accounts` (distinct reported
  accounts). One graph, one perfometer.

## Inventory

Table `software > applications > service_accounts`, one row per service that
does not run under a built-in kind (default `builtin_kinds`; inventory
plugins get no check parameters):

- Key column: `service`.
- Inventory columns: `display_name`, `account`, `kind`, `start_mode`.
- Status column: `state`.

`inventory_ui` defines the titles and makes the table available as a view and
data source for cross-host searches ("where is this account used").

## Tests

- pytest: parser (incl. empty fields, error line, German account names),
  kind classification by SID and by name, check logic for every parameter,
  change detection, inventory rows, building both rule forms, bakery output.
- Dev site: test host with canned output in `temp/`
  (`.devcontainer/test-host.sh`), discovery and check run.
- The PowerShell script cannot run in the devcontainer; it has to be verified
  on a real Windows host (German and English OS, domain member, service with
  a deleted account).

Test data uses fictional names only (CONTOSO, SRV-APP01, round SIDs).

## Not in scope

- Linux (systemd units and their users).
- Scheduled tasks, IIS application pools and other places that store
  credentials.
- Checking whether an account is privileged, e.g. member of Domain Admins.
- One service per account or per Windows service.

## Amendments from the implementation

- `discovered_services` holds every service that has an account, also the
  ones running as LocalSystem (found in the branch review: otherwise a
  service switched from LocalSystem to a service account is not a `changed`
  finding, and with Local System not built-in every service is `added`).
  It maps a service name to `{"account": <name>, "sid": <SID or "">}`. Accounts are compared by SID if both sides have one,
  otherwise by name ignoring case, so a SID that cannot be translated on one
  agent run is not a change.
- A pattern is also tried against `<computer name>\name` if the service is
  configured with `.\name`.
- An invalid pattern yields an UNKNOWN result naming the pattern.
- With `ignore_disabled`, disabled services are also left out of the change
  detection.
- A discovery during a plugin error stores no baseline; without a baseline
  and during a plugin error there is no change detection.
- A service without an account gets the kind `no_account` instead of
  `unknown`. The kind is built-in by default, and such services are left out
  of the baseline and the change detection (per-user service instances get
  a new name with every logon). To be confirmed on a real Windows host.
- The check rule form ignores the key `discovered_services`, otherwise the
  service discovery page reports an invalid check parameter.
- Limitations: computer accounts (`DOMAIN\HOST$`) are classified as
  `managed`; a UPN without SID is classified as `domain`.
- On a domain controller the agent plugin sends an empty machine SID
  (`DomainRole` >= 4), so domain accounts are classified by name there.
- At most 10 findings are named in the summary, the worst first; further
  ones are counted ("3 more findings (see details)") and listed in the
  details. The details of an account name the reason of its state.
- If one account is configured in several spellings (same SID), patterns
  are tried against all of them.
- If an account has no SID in the current data, patterns are also tried
  against the SID remembered for that account name by the service discovery.
- The details have one line per service (`<service> (<display name>):
  <account> (<kind>), <start mode>, <state>[: <reason>]`) instead of one
  block per account; the SID is no longer shown there (user request).
- Allow list entries are `{"service": <regex, optional>, "account": <regex>}`
  (user request): an account is allowed per service; without `service` for
  every service. An account is evaluated per service, the summary names
  "1 of 2 services". Plain account patterns of older rules are migrated and
  still understood by the check.
- `not_allowed_state` defaults to WARN (user request): without a rule the
  service is WARN for every reported account. This replaces "Without a rule
  the service is always OK".
- The service is called `Windows Service Accounts` (user request, was
  `Service Accounts`).
- Inventory rule `service_accounts_inventory` with `all_services` (user
  request): the table then lists every service, also under built-in kinds.
  File `rulesets/inventory.py`.
- The inventory table is `software > os > service_accounts`, titled
  `Windows Service Accounts` (user request, was `software > applications >
  service_accounts`).
- The rules are titled `Windows Service Accounts` (user request, was
  `Service accounts (Windows)`).
- With `changes` configured but no baseline, the summary says so.
- A changed account with an unchanged name (deleted and created again) is
  reported with both SIDs.
