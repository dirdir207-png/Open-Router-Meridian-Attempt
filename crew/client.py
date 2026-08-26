from typing import Any, Dict, Optional

import requests

DEFAULT_CREW_ENDPOINT = "https://api.trycrew.com/willow/graphql"


class CrewError(RuntimeError):
    pass


class CrewAuthenticationError(CrewError):
    pass


class CrewTransportError(CrewError):
    pass


class CrewAPIError(CrewError):
    pass


class CrewUncertainWriteError(CrewTransportError):
    pass


def _looks_like_auth_error(errors) -> bool:
    text = " ".join(str(item.get("message", "")) for item in errors).lower()
    return any(term in text for term in ("unauthorized", "unauthenticated", "forbidden", "token expired", "session expired"))


class CrewClient:
    def __init__(self, credential_provider, endpoint=DEFAULT_CREW_ENDPOINT, timeout_seconds=15, session=requests):
        self.credential_provider = credential_provider
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.session = session

    def execute(self, operation_name: str, query: str, variables: Optional[Dict[str, Any]] = None, *, is_mutation: bool = False) -> Dict[str, Any]:
        token = self.credential_provider.get_bearer_token()
        if not token:
            raise CrewAuthenticationError("Crew credential is missing")

        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        }
        payload = {
            "operationName": operation_name,
            "variables": variables or {},
            "query": query,
        }

        try:
            response = self.session.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            if is_mutation:
                raise CrewUncertainWriteError("Crew write outcome is uncertain; verify state before retrying") from exc
            raise CrewTransportError("Crew is unreachable") from exc

        if response.status_code in (401, 403):
            raise CrewAuthenticationError("Crew rejected the current credential")

        try:
            body = response.json()
        except ValueError as exc:
            raise CrewAPIError("Crew returned an invalid response") from exc

        errors = body.get("errors") or []
        if errors:
            if _looks_like_auth_error(errors):
                raise CrewAuthenticationError("Crew rejected the current credential")
            message = str(errors[0].get("message") or "Crew GraphQL request failed")
            raise CrewAPIError(message)

        return body.get("data") or {}
