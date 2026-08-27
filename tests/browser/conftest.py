"""Shared setup for browser tests: the single-tenant owner must exist."""

import json
import os
import urllib.error
import urllib.request

APP_URL = os.getenv("APP_URL")
OWNER_PASSWORD = "meridian-owner-2026"


def ensure_owner() -> None:
    """Register the owner once; tolerate reruns where registration is disabled."""
    if not APP_URL:
        return
    body = json.dumps(
        {
            "username": "owner",
            "email": "owner@meridian.local",
            "password": OWNER_PASSWORD,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{APP_URL}/api/auth/register",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
    except urllib.error.HTTPError as error:
        assert error.code == 403, f"Unexpected registration outcome: {error.code}"
