"""Search origins supported by the reader's public Azure cloud audience."""

import re

from grz_core.contracts import ContractError


def validate_search_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or re.fullmatch(
        r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.search\.windows\.net/?",
        endpoint,
    ) is None:
        raise ContractError(
            "ENDPOINT_INVALID",
            "Search endpoint must be a canonical https://<service>.search.windows.net origin; "
            "userinfo, ports, paths, queries, fragments and other cloud/custom hosts are unsupported",
        )
    return endpoint.rstrip("/")
