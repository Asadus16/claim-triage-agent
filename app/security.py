"""API-key auth for the service. n8n sends the key in the X-API-Key header."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    expected = get_settings().service_api_key
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
