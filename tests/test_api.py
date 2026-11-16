"""Protocol boundaries and failures that affect real devices."""

import asyncio
import gzip
import json
from collections import defaultdict, deque
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.motionblinds_hybrid.api import (
    AuthenticationError,
    Blind,
    CloudClient,
    CloudError,
    LocalClient,
    LocalError,
    battery_percent,
    password_hash,
)

GATEWAY = "AABBCCDDEEFF"
BLIND = Blind("AA:BB:CC:00:00:01", "Office blind")
USER = {"userCode": "fixture-account"}


def user_response():
    return {"retCode": "20000", "userData": gzip.compress(json.dumps(USER).encode()).hex()}


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
async def server(monkeypatch):
    """Use real HTTP framing instead of mocking aiohttp's private response API."""
    pending, received = defaultdict(deque), []

    async def handle(request):
        received.append(dict(await request.post()))
        if not pending[request.path]:
            return web.Response(status=500)
        return web.json_response(pending[request.path].popleft())

    app = web.Application()
    app.router.add_post("/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(
        "custom_components.motionblinds_hybrid.api.BASE_URL", f"http://127.0.0.1:{port}"
    )
    yield pending, received
    await runner.cleanup()


def authorize(client):
    client._access_token = "original-token"
    client._refresh_token = "refresh-token"


async def test_metadata_maps_mac_not_list_order(session, server):
    client = CloudClient(session, "fixture@example.invalid", "unused")
    authorize(client)
    pending, _ = server
    pending["/userCenter/userService/getUserInfo"].append(user_response())
    pending["/userCenter/deviceService/listWithSlaves"].append(
        {
            "retCode": "20000",
            "devices": [
                {
                    "mac": "OTHER",
                    "childs": [
                        {
                            "mac": BLIND.mac,
                            "deviceType": "10000000",
                            "deviceAlias": "Wrong gateway",
                        }
                    ],
                },
                {
                    "mac": GATEWAY,
                    "deviceAlias": "Bridge",
                    "childs": [
                        {
                            "mac": "unmatched",
                            "deviceType": "10000000",
                            "deviceAlias": "Not local",
                        },
                        {
                            "mac": BLIND.mac,
                            "deviceType": "10000000",
                            "deviceAlias": "Office blind",
                        },
                    ],
                },
            ],
        }
    )
    metadata = await client.metadata(GATEWAY, {BLIND.identity})
    assert metadata.blinds == (BLIND,)
    assert metadata.gateway_name == "Bridge"
    assert metadata.account_id == USER["userCode"]


async def test_auth_rejection_refreshes_then_retries(session, server):
    client = CloudClient(session, "fixture@example.invalid", "unused")
    authorize(client)
    pending, posts = server
    pending["/userCenter/deviceService/deviceControl"].append({"retCode": "20102"})
    pending["/userCenter/user/refreshToken"].append(
        {
            "retCode": "20000",
            "accessToken": "new-token",
            "refreshToken": "new-refresh",
        }
    )
    pending["/userCenter/deviceService/deviceControl"].append({"retCode": "20000"})
    await client.command(BLIND, {"targetPosition": 10})
    assert [d["accessToken"] for d in posts if "targetPosition" in d] == [
        "original-token",
        "new-token",
    ]


async def test_timed_out_command_is_not_retried(session):
    client = CloudClient(session, "fixture@example.invalid", "unused")
    authorize(client)
    with patch.object(session, "post", side_effect=TimeoutError()) as post:
        with pytest.raises(CloudError, match="could not be confirmed"):
            await client.command(BLIND, {"operation": 1})
        assert post.call_count == 1


async def test_concurrent_initial_auth_uses_one_login(session):
    client = CloudClient(session, "fixture@example.invalid", "unused")
    with patch.object(client, "_login", new=AsyncMock()) as login:

        async def logged_in():
            await asyncio.sleep(0)
            client._access_token = "fixture"

        login.side_effect = logged_in
        await asyncio.gather(client._authenticate(), client._authenticate())
        assert login.await_count == 1


async def test_api_error_does_not_expose_credentials(session, server):
    client = CloudClient(session, "fixture@example.invalid", "private-password")
    pending, _ = server
    pending["/userCenter/user/login"].append(
        {
            "retCode": "40102",
            "retMsg": "private-password private-token",
        }
    )
    with pytest.raises(AuthenticationError) as exc:
        await client._login()
    assert "private" not in str(exc.value)


async def test_local_reads_without_access_token_and_checks_identity():
    client = LocalClient("192.0.2.1")
    response = {"msgType": "ReadDeviceAck", "mac": BLIND.mac, "data": {"currentPosition": 10}}
    with patch.object(client, "_request", return_value=response) as request:
        assert (await client.read(BLIND))["currentPosition"] == 10
    payload = request.call_args.args[0]
    assert payload["msgType"] == "ReadDevice"
    assert "AccessToken" not in payload
    response["mac"] = "different"
    with patch.object(client, "_request", return_value=response), pytest.raises(LocalError):
        await client.read(BLIND)


@pytest.mark.parametrize(("raw", "app", "ha"), [(1084, 20, 28), (1191, 100, 79), (1075, 20, 23)])
def test_battery_methods_are_explicit(raw, app, ha):
    data = {"voltageMode": 1, "batteryLevel": raw}
    assert battery_percent(data, "app_indicator") == app
    assert battery_percent(data, "ha_estimate") == ha
    assert battery_percent({**data, "voltageMode": 0}, "app_indicator") is None


def test_password_hash_matches_decompiled_java_preprocessing():
    # Deterministic preprocessing was independently checked using Java MessageDigest.
    import bcrypt

    material = b"MDM2ZTU5N2Y0NzRlMDRhZQ=="
    assert bcrypt.checkpw(material, password_hash("REA public compatibility fixture").encode())


@pytest.mark.parametrize(
    "data",
    [
        {"targetPosition": -1},
        {"targetPosition": True},
        {"operation": 7},
        {"targetPosition": 10, "operation": 1},
    ],
)
async def test_rejects_invalid_commands_before_network(session, data):
    client = CloudClient(session, "fixture@example.invalid", "unused")
    with patch.object(client, "request", new=AsyncMock()) as request:
        with pytest.raises(ValueError):
            await client.command(BLIND, data)
        request.assert_not_called()
