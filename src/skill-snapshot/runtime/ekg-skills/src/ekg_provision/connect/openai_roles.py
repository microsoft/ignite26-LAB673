"""Read-only OpenAI grant coverage, not a general effective-access evaluator."""

import re
from typing import Any, Callable
from urllib.parse import urlsplit

from ekg_core.az_identity import IdentityError
from .spec import ARM, ConnectSpec, _get

API_VERSION = "2022-04-01"
REQUIRED_DATA_ACTIONS = (
    "Microsoft.CognitiveServices/accounts/OpenAI/deployments/embeddings/action",
    "Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action",
)
_ALL_PRINCIPALS = "00000000-0000-0000-0000-000000000000"
_GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"


def _within(target: str, assigned: Any) -> bool:
    if not isinstance(assigned, str) or not assigned.startswith("/"):
        return False
    ancestor = assigned.casefold().rstrip("/")
    return target.casefold() == ancestor or target.casefold().startswith(ancestor + "/")


def _matches(operation: str, patterns: list[str]) -> bool:
    # Azure's operation wildcard is '*', not fnmatch's character classes or '?'.
    return any(re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), operation,
                            re.IGNORECASE) for pattern in patterns)


def _permission_coverage(permissions: Any) -> tuple[set[str], bool]:
    if not isinstance(permissions, list) or not permissions:
        raise ValueError("permissions must be a nonempty array")
    covered: set[str] = set()
    conditional = False
    for block in permissions:
        if not isinstance(block, dict):
            raise ValueError("permission block is malformed")
        patterns = block.get("dataActions", [])
        exclusions = block.get("notDataActions", [])
        if any(not isinstance(value, list) or any(not isinstance(p, str) for p in value)
               for value in (patterns, exclusions)):
            raise ValueError("DataActions or NotDataActions is malformed")
        conditional |= bool(block.get("condition") or block.get("conditionVersion"))
        covered.update(action for action in REQUIRED_DATA_ACTIONS
                       if _matches(action, patterns) and not _matches(action, exclusions))
    return covered, conditional


class OpenAICoverage:
    """One Connect check caches ARM pages and role definitions across principals."""

    def __init__(self, spec: ConnectSpec, runner: Callable[..., Any]) -> None:
        self.spec, self.runner = spec, runner
        self.cache: dict[str, Any] = {}

    def _read(self, url: str) -> Any:
        parsed = urlsplit(url)
        key = parsed._replace(path=parsed.path.casefold()).geturl()
        if key not in self.cache:
            try:
                self.cache[key] = _get(url, self.runner)
            except IdentityError as error:
                self.cache[key] = error
        result = self.cache[key]
        if isinstance(result, IdentityError):
            raise result
        return result

    def _pages(self, scope: str, kind: str) -> list[dict[str, Any]]:
        path = f"{scope}/providers/Microsoft.Authorization/{kind}"
        url = f"{ARM}{path}?api-version={API_VERSION}&$filter=atScope()"
        seen: set[str] = set()
        rows = []
        while url:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.netloc != "management.azure.com"
                    or parsed.path.casefold() != path.casefold() or parsed.fragment or url in seen):
                raise ValueError(f"{kind} returned an unsafe or repeated nextLink")
            seen.add(url)
            result = self._read(url)
            if not isinstance(result, dict) or not isinstance(result.get("value"), list):
                raise ValueError(f"{kind} response must contain a value array")
            if any(not isinstance(row, dict) for row in result["value"]):
                raise ValueError(f"{kind} contains malformed evidence")
            rows.extend(result["value"])
            url = result.get("nextLink")
            if url is not None and not isinstance(url, str):
                raise ValueError(f"{kind} nextLink is malformed")
        return rows

    def _definition(self, resource_id: Any) -> dict[str, Any]:
        prefix = rf"(?:/subscriptions/{re.escape(self.spec.subscription_id)})?"
        if not isinstance(resource_id, str) or not re.fullmatch(
            prefix + rf"/providers/Microsoft.Authorization/roleDefinitions/{_GUID}",
            resource_id, re.IGNORECASE,
        ):
            raise ValueError("roleDefinitionId is absent or outside the bound subscription")
        result = self._read(f"{ARM}{resource_id}?api-version={API_VERSION}")
        if (not isinstance(result, dict) or
                str(result.get("id", "")).casefold() != resource_id.casefold() or
                not isinstance(result.get("properties"), dict)):
            raise ValueError(f"role definition {resource_id} returned mismatched or malformed metadata")
        return result["properties"]

    def _denies(self, scope: str, principal: str) -> tuple[str, list[str]]:
        uncertainty = []
        try:
            rows = self._pages(scope, "denyAssignments")
            for row in rows:
                props = row.get("properties")
                if (not isinstance(props, dict) or not isinstance(props.get("scope"), str)
                        or not props["scope"].startswith("/")):
                    raise ValueError("deny assignment properties or scope is malformed")
                assigned = props["scope"]
                if not _within(scope, assigned):
                    continue
                child_only = props.get("doNotApplyToChildScopes", False)
                if not isinstance(child_only, bool):
                    raise ValueError("deny child-scope applicability is malformed")
                if child_only and assigned.casefold() != scope.casefold():
                    continue
                denied, conditional = _permission_coverage(props.get("permissions"))
                if not denied:
                    continue
                principals, excluded = props.get("principals"), props.get("excludePrincipals", [])
                if any(not isinstance(items, list) or any(
                    not isinstance(p, dict) or not isinstance(p.get("id"), str)
                    or not isinstance(p.get("type"), str) for p in items)
                       for items in (principals, excluded)):
                    raise ValueError("deny principal or exclusion evidence is malformed")
                if any(p["id"].casefold() == principal.casefold() for p in excluded):
                    continue
                applies = any(p["id"].casefold() in (principal.casefold(), _ALL_PRINCIPALS)
                              for p in principals)
                unresolved = any(p["type"].casefold() not in ("user", "serviceprincipal")
                                 and p["id"] != _ALL_PRINCIPALS for p in principals)
                exclusions_unknown = any(p["type"].casefold() not in ("user", "serviceprincipal")
                                         for p in excluded)
                if not applies and not unresolved:
                    continue
                if (not applies or exclusions_unknown or conditional or props.get("condition")
                        or props.get("conditionVersion")):
                    uncertainty.append("Applicable deny condition/group/exclusion needs verification.")
                else:
                    return "denied", [f"Applicable deny {row.get('id', '(unnamed)')} blocks "
                                      f"{', '.join(sorted(denied))}."]
        except (IdentityError, ValueError) as error:
            uncertainty.append(f"Deny evidence unreadable or unsupported at {scope}: {error}")
        return ("unknown" if uncertainty else "none_observed"), uncertainty

    def check(self, principal: str, principal_type: str, scope: str, who: str) -> dict[str, Any]:
        covered: set[str] = set()
        via = []
        uncertainty = []
        try:
            assignments = self._pages(scope, "roleAssignments")
            for assignment in assignments:
                props = assignment.get("properties")
                if not isinstance(props, dict):
                    raise ValueError("role assignment properties are malformed")
                if str(props.get("principalId", "")).casefold() != principal.casefold():
                    continue
                if (props.get("principalType") is not None
                        and str(props["principalType"]).casefold() != principal_type.casefold()):
                    uncertainty.append("Assignment principal type differs from the selected identity.")
                    continue
                if not isinstance(props.get("scope"), str) or not props["scope"].startswith("/"):
                    raise ValueError("matching principal's role assignment scope is malformed")
                if not _within(scope, props.get("scope")):
                    continue
                if (props.get("condition") or props.get("conditionVersion")
                        or str(props.get("assignmentType", "")).casefold() == "eligible"):
                    uncertainty.append("Conditional or PIM-eligible assignment is not inferred.")
                    continue
                try:
                    definition = self._definition(props.get("roleDefinitionId"))
                    actions, conditional = _permission_coverage(definition.get("permissions"))
                except (IdentityError, ValueError) as error:
                    uncertainty.append(f"Assigned role definition unreadable or unsupported: {error}")
                    continue
                covered.update(actions)
                if actions:
                    via.append({"role_definition_id": props["roleDefinitionId"],
                                "role_name": definition.get("roleName"),
                                "scope": props["scope"]})
                if conditional:
                    uncertainty.append("Role permission condition needs effective-access verification.")
        except (IdentityError, ValueError) as error:
            uncertainty.append(f"Role assignments unreadable or unsupported at {scope}: {error}")
        coverage = ("covered" if covered == set(REQUIRED_DATA_ACTIONS) else
                    "unknown" if uncertainty else "not_covered")
        deny, deny_uncertainty = self._denies(scope, principal)
        uncertainty += deny_uncertainty
        return {
            "principal": who, "principal_object_id": principal, "principal_type": principal_type,
            "role": "Cognitive Services OpenAI User", "scope": scope,
            "status": ("assigned" if coverage == "covered" and deny == "none_observed"
                       and not uncertainty else "unverified"),
            "permission_coverage": coverage, "effective_access": "denied" if deny == "denied" else "unverified",
            "required_data_actions": list(REQUIRED_DATA_ACTIONS),
            "covered_data_actions": sorted(covered), "via_roles": via, "deny_evidence": deny,
            "grant_recommended": False,
            "detail": "Observed DataActions coverage is not proof of effective inference access. "
                      "Verify group membership, active PIM, conditions, denies and the caller's "
                      "network path before requesting any optional, separately approved grant.",
            "uncertainty": uncertainty + [
                "Group membership and PIM eligibility are not resolved; absence of a direct "
                "grant does not establish missing effective access.",
                "The operator's model-list probe proves neither inference access nor the "
                "Search identity's access.",
            ],
        }
