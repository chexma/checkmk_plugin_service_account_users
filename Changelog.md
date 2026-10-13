# Changelog

All notable changes to this plugin. Versions match `version` in `package`
and the release tags `v<version>`.

## [Unreleased]

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
