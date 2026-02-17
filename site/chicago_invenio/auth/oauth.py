"""Implement OAuth handlers."""

from typing import Any

import jwt
import requests
from flask import current_app
from flask_oauthlib.client import OAuthRemoteApp


def info_handler(
    remote_app: OAuthRemoteApp, response_data: dict[str, Any]
) -> dict[str, Any]:
    """Extract account info from authorisation response.

    Extracts and validates the id_token returned as part of the OIDC workflow using
    metadata from the OpenId provider. Claims from the JWT are then returned in the
    expected structure for user sign-up process.

    Requires the following claims to be present in the id_token: email,
    preferred_username, name and oid.
    """
    current_app.logger.info("Processing OAuth authentication")

    try:
        # Validate required fields
        if "id_token" not in response_data:
            raise ValueError("Missing id_token in response")

        # Fetch OIDC configuration with timeout and validation
        response = requests.get(
            current_app.config["CHI_OAUTH_WELL_KNOWN_URL"], timeout=10
        )
        response.raise_for_status()
        oidc_config = response.json()

        required_keys = ["id_token_signing_alg_values_supported", "jwks_uri", "issuer"]
        for key in required_keys:
            if key not in oidc_config:
                raise ValueError(f"Missing required OIDC config: {key}")

        signing_algos = oidc_config["id_token_signing_alg_values_supported"]
        jwks_client = jwt.PyJWKClient(oidc_config["jwks_uri"])

        id_token = response_data["id_token"]
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)

        # Validate JWT with issuer and expiration checks
        data = jwt.api_jwt.decode(
            id_token,
            key=signing_key.key,
            algorithms=signing_algos,
            audience=remote_app.consumer_key,
            issuer=oidc_config["issuer"],
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
        )

        # Validate required claims
        required_claims = ["preferred_username", "name", "sub"]
        for claim in required_claims:
            if claim not in data:
                raise ValueError(f"Missing required claim: {claim}")

        current_app.logger.info("OAuth authentication successful")

    except Exception as e:
        current_app.logger.error(f"OAuth authentication failed: {str(e)}")
        raise

    return dict(
        user=dict(
            email=data["preferred_username"],
            profile=dict(
                username=data["preferred_username"].removesuffix("@uchicago.edu"),
                full_name=data["name"],
                affiliations="University of Chicago",
            ),
        ),
        external_id=data["sub"],
        external_method="chi_sso",
        active=True,
    )
