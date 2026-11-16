"""Async cloud commands and local-only status, without HA dependencies."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import io
import json
import socket
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import aiohttp
import bcrypt

from .const import APP_CODE, BASE_URL, BLIND_TYPE

AUTH_CODES = {"20102", "20108", "40102"}
SUCCESS_CODES = {"20000", "0000"}
MAX_RESPONSE = 2 * 1024 * 1024


class CloudError(Exception):
    """Cloud communication failed; messages must never contain credentials."""


class AuthenticationError(CloudError):
    """Account authentication was rejected."""


class LocalError(Exception):
    """Local gateway communication or identity validation failed."""


def normalize_mac(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace(":", "").replace("-", "").upper()


def message_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]


def password_hash(password: str) -> str:
    first = hashlib.md5(password.encode()).hexdigest().upper()
    middle = hashlib.md5(first.encode()).hexdigest()[8:24]
    return bcrypt.hashpw(base64.b64encode(middle.encode()), bcrypt.gensalt(10, b"2a")).decode()


def decode_user(response: dict[str, Any]) -> dict[str, Any]:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(bytes.fromhex(response["userData"]))) as stream:
            raw = stream.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        user = json.loads(raw)
        if not isinstance(user, dict) or not isinstance(user.get("userCode"), str):
            raise ValueError
        return user
    except (OSError, ValueError, TypeError, KeyError, EOFError) as err:
        raise CloudError("Invalid cloud user information") from err


@dataclass(frozen=True)
class Blind:
    mac: str
    name: str
    device_type: str = BLIND_TYPE

    @property
    def identity(self) -> str:
        return normalize_mac(self.mac)


@dataclass(frozen=True)
class Metadata:
    account_id: str
    gateway_mac: str
    gateway_name: str
    blinds: tuple[Blind, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Metadata:
        return cls(
            data["account_id"],
            data["gateway_mac"],
            data["gateway_name"],
            tuple(Blind(**blind) for blind in data["blinds"]),
        )


class CloudClient:
    """Use the fixed HTTPS app API; never log request/response bodies."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def _post(self, path: str, fields: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.post(
                BASE_URL + path,
                data={**fields, "msgId": message_id()},
                headers={"Connection": "close"},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError("Cloud authentication rejected")
                if response.status != 200:
                    raise CloudError(f"Cloud HTTP error {response.status}")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE:
                        raise CloudError("Cloud response exceeds the inspection limit")
                data = json.loads(raw)
        except (aiohttp.ClientError, TimeoutError) as err:
            # A timed-out command might already have been delivered. Never retry it.
            raise CloudError("Cloud delivery could not be confirmed") from err
        except (ValueError, TypeError) as err:
            raise CloudError("Invalid cloud response") from err
        if not isinstance(data, dict):
            raise CloudError("Invalid cloud response")
        code = str(data.get("retCode", ""))
        if code not in SUCCESS_CODES:
            if code in AUTH_CODES or path == "/userCenter/user/login":
                raise AuthenticationError("Cloud account authentication rejected")
            safe_code = code if code.isdecimal() else "unknown"
            raise CloudError(f"Cloud API error {safe_code}")
        return data

    def _set_tokens(self, data: dict[str, Any]) -> None:
        access = data.get("accessToken")
        if not isinstance(access, str) or not access:
            raise AuthenticationError("Cloud returned no access token")
        self._access_token = access
        refresh = data.get("refreshToken")
        self._refresh_token = refresh if isinstance(refresh, str) and refresh else None

    async def _login(self) -> None:
        hashed = await asyncio.to_thread(password_hash, self._password)
        self._set_tokens(
            await self._post(
                "/userCenter/user/login",
                {
                    "loginName": self._username,
                    "password": hashed,
                    "version": "v2",
                    "appCode": APP_CODE,
                },
            )
        )

    async def _authenticate(self, rejected_token: str | None = None) -> None:
        async with self._auth_lock:
            if self._access_token and self._access_token != rejected_token:
                return
            if self._refresh_token and self._access_token:
                try:
                    self._set_tokens(
                        await self._post(
                            "/userCenter/user/refreshToken",
                            {
                                "refreshToken": self._refresh_token,
                                "accessToken": self._access_token,
                            },
                        )
                    )
                    return
                except AuthenticationError:
                    self._access_token = self._refresh_token = None
            await self._login()

    async def request(self, path: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._authenticate()
        used_token = self._access_token
        try:
            return await self._post(path, {**(fields or {}), "accessToken": used_token})
        except AuthenticationError:
            # Only explicit rejection permits a retry: the command was not accepted.
            await self._authenticate(rejected_token=used_token)
            return await self._post(path, {**(fields or {}), "accessToken": self._access_token})

    async def metadata(self, gateway_mac: str, local_macs: set[str]) -> Metadata:
        user = decode_user(await self.request("/userCenter/userService/getUserInfo"))
        result = await self.request("/userCenter/deviceService/listWithSlaves")
        roots = result.get("devices")
        if not isinstance(roots, list):
            raise CloudError("Invalid cloud device list")
        gateways = [
            d
            for d in roots
            if isinstance(d, dict) and normalize_mac(d.get("mac", "")) == normalize_mac(gateway_mac)
        ]
        if len(gateways) != 1:
            raise CloudError("Local gateway does not match exactly one cloud gateway")
        gateway = gateways[0]
        queue = deque(gateway.get("childs") or [])
        devices: dict[str, Blind] = {}
        while queue:
            item = queue.popleft()
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("childs"), list):
                queue.extend(item["childs"])
            mac = item.get("mac")
            if not isinstance(mac, str) or item.get("deviceType") != BLIND_TYPE:
                continue
            identity = normalize_mac(mac)
            if identity not in local_macs:
                continue
            name = item.get("deviceAlias") or f"Blind {identity[-4:]}"
            devices[identity] = Blind(mac, name)
        if not devices:
            raise CloudError("No supported blinds match the local gateway")
        return Metadata(
            user["userCode"],
            gateway_mac,
            gateway.get("deviceAlias") or "Motionblinds gateway",
            tuple(sorted(devices.values(), key=lambda d: d.identity)),
        )

    async def command(self, blind: Blind, data: dict[str, int]) -> None:
        if set(data) == {"targetPosition"}:
            value = data["targetPosition"]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError("Position must be an integer from 0 to 100")
        elif set(data) == {"operation"}:
            value = data["operation"]
            if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2, 5):
                raise ValueError("Unsupported blind operation")
        else:
            raise ValueError("Unsupported command fields")
        await self.request(
            "/userCenter/deviceService/deviceControl",
            {
                "mac": blind.mac,
                "deviceType": blind.device_type,
                **data,
            },
        )


class LocalClient:
    """Read gateway cache only. No access token or local writes are needed."""

    def __init__(self, host: str) -> None:
        self.host = host

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            address = socket.gethostbyname(self.host)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2)
                sock.connect((address, 32100))
                sock.send(json.dumps({**payload, "msgID": message_id()}).encode())
                response = json.loads(sock.recv(65536))
        except (OSError, ValueError) as err:
            raise LocalError("Local gateway did not return a valid response") from err
        if not isinstance(response, dict) or response.get("msgType") != payload["msgType"] + "Ack":
            raise LocalError("Unexpected local response type")
        if response.get("actionResult") is not None:
            raise LocalError("Local gateway rejected the read")
        return response

    async def discover(self) -> tuple[str, set[str]]:
        response = await asyncio.to_thread(self._request, {"msgType": "GetDeviceList"})
        mac, devices = response.get("mac"), response.get("data")
        if not isinstance(mac, str) or not isinstance(devices, list):
            raise LocalError("Invalid local gateway discovery")
        return normalize_mac(mac), {
            normalize_mac(d["mac"])
            for d in devices
            if isinstance(d, dict)
            and isinstance(d.get("mac"), str)
            and d.get("deviceType") == BLIND_TYPE
        }

    async def read(self, blind: Blind) -> dict[str, Any]:
        response = await asyncio.to_thread(
            self._request,
            {
                "msgType": "ReadDevice",
                "mac": blind.mac,
                "deviceType": blind.device_type,
            },
        )
        if normalize_mac(response.get("mac", "")) != blind.identity:
            raise LocalError("Local response belongs to a different blind")
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("currentPosition"), int):
            raise LocalError("Invalid blind status")
        position = data["currentPosition"]
        if isinstance(position, bool) or not 0 <= position <= 100:
            raise LocalError("Invalid blind position")
        return data


def battery_percent(data: dict[str, Any], method: str) -> int | None:
    raw = data.get("batteryLevel")
    if data.get("voltageMode") != 1 or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    voltage = raw / 100
    if method == "app_indicator":
        bands = (
            (6.8, 7.0, 0),
            (7.0, 7.09, 10),
            (7.09, 7.28, 20),
            (7.28, 7.56, 50),
            (7.56, 8.8, 100),
            (8.8, 10.57, 0),
            (10.57, 10.7, 10),
            (10.7, 10.95, 20),
            (10.95, 11.35, 50),
            (11.35, 13.2, 100),
            (13.2, 14.0, 0),
            (14.0, 14.2, 10),
            (14.2, 14.5, 20),
            (14.5, 15.9, 50),
            (15.9, 19.0, 100),
        )
        return next((percent for low, high, percent in bands if low <= voltage < high), None)
    if 0 < voltage <= 9.4:
        low, high = 6.2, 8.4
    elif 9.4 < voltage <= 13.6:
        low, high = 10.27, 12.34
    elif 13.6 < voltage <= 19:
        low, high = 14.6, 16.8
    else:
        return None
    return max(0, min(100, round((voltage - low) * 100 / (high - low))))
