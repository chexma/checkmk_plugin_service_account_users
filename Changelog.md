# Changelog

All notable changes to this plugin. Versions match `version` in `package`
and the release tags `v<version>`.

## [Unreleased]

## [2.5.10] - 2026-10-13

- All internal names are now `windows_service_accounts`: check plugin,
  agent section, the three rulesets (`windows_service_accounts`,
  `windows_service_accounts_inventory`), bakery plugin, inventory path
  (`software > os > windows_service_accounts`), graph, perfometer and man
  page. Metric names and the view `invserviceaccounts` are unchanged.
  After the update:
  1. Create the rules again (service, agent bakery, HW/SW inventory): rules
     of the old rulesets are no longer evaluated.
  2. Bake and deploy the agents: the new check only reads the section
     `<<<windows_service_accounts>>>`.
  3. Run the service discovery on the hosts and remove the vanished service
     of the old check.
- Man page: distribution is the author.

## [2.5.9] - 2026-10-13

- The plugin files are named `windows_service_accounts.*`, including the
  agent plugin, which is now `windows_service_accounts.ps1`. Bake and
  deploy the agents after the update; remove a manually copied
  `service_accounts.ps1` from the hosts, otherwise the section is sent
  twice. Check, section and rule names are unchanged.

## [2.5.8] - 2026-10-13

- The plugin directory is now `windows_service_accounts` (was
  `service_accounts`). Check, section and rule names are unchanged.

## [2.5.7] - 2026-10-13

- The MKP is now called `windows_service_accounts` (was
  `service_accounts`). Remove the old package before installing the new
  one: both contain the same files. Rules and services are kept.

## [2.5.6] - 2026-10-13

- The three rules (service, agent bakery, HW/SW inventory) are now called
  `Windows Service Accounts` (was `Service accounts (Windows)`).
- Fix: the man page had a duplicated, broken section since 2.5.5.

## [2.5.5] - 2026-10-13

- The inventory table moved to `Software > Operating system > Windows
  Service Accounts` (was `Software > Applications > Service accounts`).
- HW/SW inventory rule `Service accounts (Windows)`: optionally list every
  Windows service in the inventory table, also the ones under built-in
  accounts.

## [2.5.4] - 2026-10-13

- The service is now called `Windows Service Accounts` (was `Service
  Accounts`): run the service discovery on the hosts after the update.
- Manifest: author and download URL.

## [2.5.3] - 2026-10-13

- Allow list entries have a service pattern and an account pattern: an
  account can be allowed for certain services only. Existing rules keep
  working (entries without service).
- Default changed: without a rule, accounts that are not on the allow list
  are WARN (was OK). Set the state to OK in the rule to only show them.
- Details: one line per service with its account instead of one block per
  account.
- License headers in the source files.

## [2.5.2] - 2026-10-13

- License is GPLv3 (`LICENSE`, man page); README for the plugin.

## [2.5.1] - 2026-10-13

- Summary names at most 10 findings (worst first), the rest is counted and
  listed in the details; the details of an account name the reason.
- Patterns match every spelling of an account and fall back to the SID from
  the service discovery if the agent could not translate the account.
- Hint in the summary if changes are configured but there is no baseline.
- Changed account with the same name is reported with both SIDs.
- Agent plugin: no machine SID query on domain controllers.
- Fixes: doubled backslashes in the invalid pattern message, crash on a
  malformed baseline.

## [2.5.0] - 2026-10-13

- Initial implementation: agent plugin `service_accounts.ps1` with bakery
  rule, service `Service Accounts` with check parameters, metrics and graph,
  HW/SW inventory table with view. The agent plugin is not yet verified on
  Windows hosts.
