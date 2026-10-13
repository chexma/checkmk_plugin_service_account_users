#!/usr/bin/env python3
# Copyright (C) 2026 chexma - License: GNU General Public License v3
# This file is part of the Checkmk plugin service_accounts. It is subject to the
# terms and conditions defined in the file LICENSE in the root of the repository.
# SPDX-License-Identifier: GPL-3.0-only
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
        # The baseline the service discovery stores next to the rule parameters.
        ignored_elements=("discovered_services",),
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
                        MultipleChoiceElement(
                            name="no_account", title=Title("Services without an account")
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
                        [
                            "local_system",
                            "local_service",
                            "network_service",
                            "virtual",
                            "no_account",
                        ]
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
