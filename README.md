# Checkmk plugin: Windows Service Accounts

Shows which Windows services do not run under a built-in system account
(Local System, Local Service, Network Service, `NT SERVICE\...`) but under a
service account: a domain account, a local user or a managed service account.
Optionally alerts on accounts that are not allowed, on unwanted accounts and
on changes since the service discovery.

- One service `Windows Service Accounts` per Windows host
- HW/SW inventory table with a view to search an account across all hosts
- Agent plugin `windows_service_accounts.ps1`, deployed with the agent bakery

Status: the server side is tested (pytest, Checkmk 2.5.0p15 site with canned
agent output). The PowerShell agent plugin has run on one German Windows
server so far; domain accounts, deleted accounts and domain controllers are
not verified on real hosts yet.

## Requirements

- Checkmk 2.5. The version number of the plugin follows the Checkmk release:
  2.5.x is for Checkmk 2.5.
- A commercial edition for the agent bakery. Without the bakery, copy
  `windows_service_accounts.ps1` to the plugin directory of the Windows agent by hand.
- Windows hosts with PowerShell 5.1 or newer.

The plugin uses the APIs `cmk.bakery.v2_unstable` and
`cmk.inventory_ui.v1_unstable`, which Checkmk declares unstable in 2.5; a later
Checkmk release may need an adapted plugin version.

## Installation

Upload the MKP in *Setup > Extension packages* and enable it, or on the command
line as site user:

```bash
mkp add windows_service_accounts-<version>.mkp
mkp enable windows_service_accounts <version>
```

Up to version 2.5.6 the package was called `service_accounts`. Remove that
package before installing `windows_service_accounts` (*Extension packages*, or
`mkp disable service_accounts` and `mkp remove service_accounts <version>`):
both contain the same files.

Since 2.5.10 all internal names are `windows_service_accounts` too (check
plugin, agent section, rulesets). When updating from an older version, create
the rules again, bake and deploy the agents and run the service discovery on
the hosts.

## Setup

1. *Setup > Agents > Windows, Linux, Solaris, AIX > Agent rules > Windows
   Service Accounts*: create a rule with *Deploy the plugin* for the Windows
   hosts. Optionally let the plugin run asynchronously with a cache interval
   (suggested: 1 hour); useful where translating accounts takes long because a
   domain is not reachable.
2. Bake and deploy the agents.
3. Run the service discovery on the hosts. Each host gets the service
   `Windows Service Accounts`.
4. For the inventory table the HW/SW inventory has to be enabled for the hosts
   (rule *Do HW/SW inventory*).

Without a rule the service is WARN for every service that runs under a
service account: accounts have to be allowed explicitly (see the rule below).

## Service

Summary, for example:

```text
5 services under 4 service accounts, CONTOSO\old_admin: not on the allow list (1 service)(!)
```

The details have one line per service with its account, the kind of the
account, start mode and state, and the reason if the account is not OK:

```text
Legacy (Legacy App): CONTOSO\old_admin (domain account), Auto, Stopped: not on the allow list
MSSQLSERVER (SQL Server): CONTOSO\svc_sql (domain account), Auto, Running
SQLAgent (SQL Server Agent): CONTOSO\svc_sql (domain account), Manual, Stopped
```

At most 10 findings are named in the summary, the worst first; further ones
are counted there and listed in the details.

Metrics: number of services under service accounts and number of distinct
service accounts, with a graph and a perfometer.

### Account kinds

Every account gets a kind, by its SID if the agent could translate the
account, otherwise by its name:

| Kind | Recognised by | Built-in by default |
|---|---|---|
| Local System | `S-1-5-18`, `LocalSystem` | yes |
| Local Service | `S-1-5-19` | yes |
| Network Service | `S-1-5-20` | yes |
| Virtual account | `S-1-5-80-*`, `NT SERVICE\...` | yes |
| No account | empty account, e.g. per-user service instances | yes |
| Local user | SID of the computer, `.\name`, `<computer>\name` | no |
| Managed service account | domain SID and name ends with `$` | no |
| Domain account | any other domain SID, `DOMAIN\name`, `name@domain` | no |
| Unknown | anything else | no |

Services under built-in kinds are not reported. Because the kind comes from
the SID, this works independently of the language of the operating system.

### Rule *Windows Service Accounts*

*Setup > Services > Service monitoring rules*. All settings are optional.

| Setting | Effect |
|---|---|
| Built-in accounts | Which kinds are unremarkable and not reported |
| Disabled services | Ignore services with the start mode Disabled (by default they are evaluated: Windows keeps their credentials) |
| Allowed accounts | Which account may run which services: a pattern for the account and optionally one for the service names. Without services the account is allowed for every service of the host. Allowed combinations are OK and exempt from the other settings |
| Additional allowed accounts | Like the allow list, but added to the list of a more general rule instead of replacing it |
| State for accounts that are not allowed | State for every service whose account is not on the allow list. Default WARN; set it to OK to only show the accounts |
| Unwanted accounts | Patterns with a state, e.g. for personal or administrator accounts; the first matching entry counts |
| Changes since the service discovery | States for added services, changed accounts and removed services |
| State if the agent plugin reported an error | Default UNKNOWN |

Patterns are regular expressions that have to match the whole account,
ignoring case. They are tried against the account name as configured in the
service and against its SID:

- A backslash is written as `\\`: `CONTOSO\\svc_.*`
- The service pattern of an allow list entry is matched against the internal
  service name (the first word of each details line), not the display name:
  `MSSQLSERVER|SQLSERVERAGENT`, or `MSSQL\$.*` for all instances.
- `$HOSTNAME$` is replaced by the computer name: `$HOSTNAME$\\backup` matches
  the local user `backup` on every host, also if the service is configured
  with `.\backup`.
- An account configured in several spellings (`CONTOSO\svc_sql` and
  `svc_sql@contoso.example`) is matched under each of them.

### Changes since the service discovery

The service discovery remembers the account of every service. With the
setting *Changes since the service discovery* the check reports differences
for services whose old or new account is a reported account that is not on
the allow list:

- a new service
- a service whose account changed, e.g. from Local System to a domain account
- a service that no longer exists

To accept a change, update the service parameters in the service discovery of
the host. Services without an account are left out of the comparison.

## Inventory

Table *Software > Operating system > Windows Service Accounts* with one row
per service that does not run under a built-in kind: service, display name,
account, kind, start mode and state. A host on which every service runs under
a built-in account has no such table.

With the rule *Windows Service Accounts* under *Setup > Hosts > HW/SW
inventory rules* the table can list every Windows service instead, also the
ones under built-in accounts; the column *Kind* tells them apart.

The view *Windows Service Accounts* (search: `invserviceaccounts_search`)
finds the hosts and services that use an account; it shows rows after a
filter was submitted.

## Limitations

- Computer accounts (`DOMAIN\HOST$`) are shown as managed service accounts.
- An account in UPN notation that cannot be translated to a SID is shown as
  domain account.
- On a domain controller the accounts are classified by name, because there
  are no local accounts to tell the machine SID from.
- While the agent plugin reports an error, the inventory table is empty.
- Not covered: scheduled tasks, IIS application pools and other places that
  store credentials; whether an account is privileged; Linux.

## Agent output

```text
<<<windows_service_accounts:sep(124)>>>
computer|<computer name>|<machine SID>
service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
error|<message>
```

The plugin reports every service unfiltered and has no configuration file:
all evaluation happens on the Checkmk server, so changing a rule never
requires baking agents.

## Development

The repo is based on
[checkmk-plugin-template](https://github.com/chexma/checkmk-plugin-template)
(devcontainer with a Checkmk site; see its README for the environment).

```bash
.devcontainer/ci.sh                    # lint, tests, cmk-validate-plugins
.devcontainer/build.sh                 # build the MKP from ./package
.devcontainer/test-host.sh <host> <agent-output-file>   # host with canned agent output
```

Design and decisions: `docs/superpowers/specs/2026-10-13-service-accounts-design.md`.
Changes: `Changelog.md`.

## License

GNU General Public License v3, see `LICENSE`.
