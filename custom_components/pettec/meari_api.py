"""Minimal Meari cloud API client used by the PetTec HA integration.

Reverse-engineered from the Snoop Cube Android app (com.pettec.snoopcube).
Auth flow:
  POST /meari/app/login (3DES password, X-Ca-* signed)
  → returns userToken, pfKey.{accessid,accesskey,openapiDomain}, country/phone codes.
Subsequent calls go to the user's regional API (apis-eu-frankfurt.cloudedge360.com)
for device list, and to pfKey.openapiDomain for IoT device-config (the feed cmd).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlencode
from datetime import datetime, timezone

import aiohttp
import pyDes


_LOGGER = logging.getLogger(__name__)


# Snoop Cube AndroidManifest.xml meta-data
APP_KEY = "aTCOXp79xCGLFdb1HfBAPoQadWMdFsIF"
APP_SECRET = "txcAJ2ec+D3nUYRHaXfriovwW9xhUUEC"
SOURCE_APP = 11
APP_VER = "5.10.1"
APP_VER_CODE = 510
DES_KEY = "123456781234567812345678"
DES_IV = "01234567"

DEFAULT_BASE_URL = "https://apis.cloudedge360.com"
RESULT_OK = "1001"
RESULT_LOGGED_ELSEWHERE = "1023"  # "Your account logged in elsewhere..."

# IoT property IDs (from APK IotConstants.java)
IOT_PROP_PET_FEED2 = "850"


class MeariAuthError(Exception):
    """Authentication failed (bad credentials)."""


class MeariSessionBumpedError(Exception):
    """Session was invalidated by another login (1023)."""


class MeariApiError(Exception):
    """API call failed for some other reason."""


# ---- crypto helpers ----------------------------------------------------------

def _triple_des_encrypt(plaintext: str) -> str:
    des = pyDes.triple_des(key=DES_KEY, mode=pyDes.CBC, padmode=pyDes.PAD_PKCS5, IV=DES_IV)
    return base64.b64encode(des.encrypt(plaintext)).decode()


def _hmac_sha1_b64url(message: str, key: str) -> str:
    sig = hmac.new(key.encode(), message.encode(), hashlib.sha1).digest()
    return base64.urlsafe_b64encode(sig).decode()


def _hmac_sha1_b64(message: str, key: str) -> str:
    sig = hmac.new(key.encode(), message.encode(), hashlib.sha1).digest()
    return base64.b64encode(sig).decode()


def _now_ms() -> int:
    return round(time.time() * 1000)


def _sign_headers(api_path: str, key: str, secret: str) -> dict[str, str]:
    """X-Ca-* request headers. For login: APP_KEY/APP_SECRET. For authed: userToken/userToken."""
    timestamp = str(_now_ms())
    nonce = str(random.randint(100000, 999999))
    sign_input = f"api={api_path}|X-Ca-Key={key}|X-Ca-Timestamp={timestamp}|X-Ca-Nonce={nonce}"
    return {
        "X-Ca-Key": key,
        "X-Ca-Nonce": nonce,
        "X-Ca-Sign": _hmac_sha1_b64url(sign_input, secret),
        "X-Ca-Timestamp": timestamp,
        "content-type": "application/x-www-form-urlencoded",
    }


# ---- types -------------------------------------------------------------------

@dataclass
class MeariSession:
    user_id: str
    user_token: str
    country_code: str
    phone_code: str
    access_id: str
    access_key: str
    openapi_domain: str
    base_url: str  # regional API server picked from imageUrl
    raw: dict[str, Any] = field(default_factory=dict)


# ---- client ------------------------------------------------------------------

class MeariClient:
    """Minimal Meari client. Holds one session per email/password."""

    def __init__(
        self,
        http: aiohttp.ClientSession,
        email: str,
        password: str,
        country_code: str = "DE",
        phone_code: str = "49",
    ):
        self._http = http
        self._email = email
        self._password = password
        self._country = country_code
        self._phone = phone_code
        self.session: MeariSession | None = None

    async def _post_form(
        self, base_url: str, api_path: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{base_url}{api_path}"
        sign_path = "/ppstrongs/" + api_path
        if self.session and self.session.user_token:
            headers = _sign_headers(sign_path, self.session.user_token, self.session.user_token)
            auth_kind = f"userToken={self.session.user_token[:8]}…"
        else:
            headers = _sign_headers(sign_path, APP_KEY, APP_SECRET)
            auth_kind = "APP_KEY"
        body = urlencode(data)
        _LOGGER.debug("PetTec → POST %s  auth=%s  body_len=%d", url, auth_kind, len(body))
        async with self._http.post(url, data=body, headers=headers) as resp:
            text = await resp.text()
            _LOGGER.debug(
                "PetTec ← HTTP %s from %s  body[:300]=%s",
                resp.status, url, text[:300].replace("\n", "\\n"),
            )
            try:
                return json.loads(text)
            except json.JSONDecodeError as err:
                raise MeariApiError(f"non-JSON response from {url}: {text[:200]}") from err

    async def login(self) -> MeariSession:
        body = {
            "phoneType": "a",
            "sourceApp": SOURCE_APP,
            "appVer": APP_VER,
            "iotType": 3,
            "lngType": "en",
            "userAccount": self._email,
            "password": _triple_des_encrypt(self._password),
            "phoneCode": self._phone,
            "appVerCode": APP_VER_CODE,
            "t": str(_now_ms()),
            "countryCode": self._country,
        }
        resp = await self._post_form(DEFAULT_BASE_URL, "/meari/app/login", body)
        if resp.get("resultCode") != RESULT_OK:
            raise MeariAuthError(f"login failed: resultCode={resp.get('resultCode')}")

        result = resp.get("result", {}) or {}
        iot = result.get("iot", {}) or {}
        pfkey = iot.get("pfKey", {}) or {}

        # Pick regional base URL from avatar host (login is global, data APIs are regional)
        avatar = result.get("imageUrl", "") or ""
        base_url = DEFAULT_BASE_URL
        if "apis-" in avatar and ".cloudedge360.com" in avatar:
            host = urlparse(avatar).netloc
            base_url = f"https://{host}"

        self.session = MeariSession(
            user_id=str(result.get("userID", "")),
            user_token=result.get("userToken", "") or "",
            country_code=result.get("countryCode") or self._country,
            phone_code=result.get("phoneCode") or self._phone,
            access_id=pfkey.get("accessid", "") or "",
            access_key=pfkey.get("accesskey", "") or "",
            openapi_domain=pfkey.get("openapiDomain", "") or "",
            base_url=base_url,
            raw=resp,
        )
        if not (self.session.user_token and self.session.access_key and self.session.openapi_domain):
            raise MeariAuthError("login response missing token / pfKey")
        return self.session

    def _signed_body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """RequestParams(5) body — body-signed with userToken as HMAC key."""
        if not self.session:
            raise MeariApiError("not logged in")
        ts_ms = _now_ms()
        iso_ts = (
            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S."
            )
            + f"{ts_ms % 1000:03d}UTC"
        )
        params: dict[str, Any] = {
            "phoneType": "a",
            "appVer": APP_VER,
            "appVerCode": str(APP_VER_CODE),
            "lngType": "en",
            "t": str(ts_ms),
            "sourceApp": str(SOURCE_APP),
            "userID": self.session.user_id,
            "countryCode": self.session.country_code,
            "phoneCode": self.session.phone_code,
            "signatureMethod": "HMAC-SHA1",
            "timestamp": iso_ts,
            "signatureVersion": "1.0",
            "signatureNonce": str(ts_ms),
        }
        if extra:
            params.update({k: str(v) for k, v in extra.items()})

        canonical = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        params["signature"] = _hmac_sha1_b64(canonical, self.session.user_token)
        return params

    async def get_device_list(self) -> dict[str, Any]:
        """Returns {nvr: [...], ipc: [...], snap: [...], chime: [...]}.

        NOTE: the decompiled SDK passes deviceTypeId=2 here, but doing so
        makes the server return 1023 ("logged in elsewhere"). Empirically the
        server only accepts this call WITHOUT that field. Likely the SDK
        constant drifted from what the live server expects.
        """
        if not self.session:
            raise MeariApiError("not logged in")
        resp = await self._post_form(
            self.session.base_url,
            "/v1/app/device/info/get",
            self._signed_body(),
        )
        rc = resp.get("resultCode")
        if rc == RESULT_OK:
            return resp
        if rc == RESULT_LOGGED_ELSEWHERE:
            raise MeariSessionBumpedError(f"device list: resultCode={rc} (logged in elsewhere)")
        raise MeariApiError(f"device list failed: resultCode={rc}")

    # ---- IoT openapi (device control) ----------------------------------------
    #
    # IoT control goes through a different endpoint than the cloud REST API:
    # GET {pfKey.openapiDomain}/openapi/device/config?accessid=…&expires=…
    #     &signature=…&action=set&deviceid=<formatSn(snNum)>&params=<base64 JSON>
    #
    # Signature: base64(HMAC-SHA1("GET\n\n\n{expires}\n{path}\n{action}", access_key))
    # formatSn:  9-char SN → "0"+sn ; else SN[4:]  (PetTec UIDs are 20 chars: drop "ppsl"/"ppsc"/"ppil"/etc prefix)

    @staticmethod
    def _format_sn(sn: str) -> str:
        if not sn:
            return ""
        if len(sn) == 9:
            return "0" + sn
        return sn[4:]

    @staticmethod
    def _expires_str() -> str:
        """Match SdkUtils.getTimeOut(): now + 60s, then subtract local TZ offset."""
        now_ms = _now_ms() + 60_000
        local = time.localtime(now_ms / 1000)
        tz_offset_ms = local.tm_gmtoff * 1000
        adjusted_ms = now_ms - tz_offset_ms
        return str(adjusted_ms // 1000)

    @staticmethod
    def _build_iot_params_b64(iot_props: dict[str, str]) -> str:
        body = {
            "code": 100001,
            "action": "set",
            "name": "iot",
            "iot": iot_props,
        }
        return base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()

    async def set_iot_property(self, sn_num: str, props: dict[str, str]) -> dict[str, Any]:
        """Send action=set for IoT properties on a device. props: {prop_id: value}."""
        if not self.session:
            raise MeariApiError("not logged in")
        path = "/openapi/device/config"
        action = "set"
        expires = self._expires_str()
        sign_input = f"GET\n\n\n{expires}\n{path}\n{action}"
        signature = _hmac_sha1_b64(sign_input, self.session.access_key)

        query = {
            "accessid": self.session.access_id,
            "expires": expires,
            "signature": signature,
            "action": action,
            "deviceid": self._format_sn(sn_num),
            "params": self._build_iot_params_b64(props),
        }
        url = self.session.openapi_domain.rstrip("/") + path
        async with self._http.get(url, params=query) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as err:
                raise MeariApiError(f"non-JSON response from {url}: {text[:200]}") from err
            if isinstance(data, dict) and data.get("errid"):
                raise MeariApiError(f"device config set failed: {data}")
            return data

    async def feed_one_portion(self, sn_num: str, portions: int = 1) -> dict[str, Any]:
        """Trigger N portions on a Cam Buddy (or compatible feeder)."""
        return await self.set_iot_property(
            sn_num,
            {IOT_PROP_PET_FEED2: json.dumps({"parts": portions}, separators=(",", ":"))},
        )

    async def list_feeders_with_retry(self, retries: int = 5) -> list[dict[str, Any]]:
        """list_feeders() with automatic re-login on 1023 (session bumped).

        Meari only allows ONE active session per account. Any second login
        from anywhere — phone, second HA instance, the Snoop Cube web UI —
        invalidates ours. We re-login between attempts; whoever logs in last
        wins. With a small backoff between retries, we usually win within a
        couple of tries unless something is _actively_ logging in.
        """
        import asyncio as _asyncio
        for attempt in range(retries + 1):
            try:
                return await self.list_feeders()
            except MeariSessionBumpedError:
                if attempt == retries:
                    raise
                _LOGGER.info(
                    "PetTec session bumped (attempt %d/%d) — re-logging in",
                    attempt + 1,
                    retries,
                )
                await _asyncio.sleep(0.5 + attempt * 0.5)
                await self.login()
        return []  # unreachable

    # ---- helper: enumerate feeders ------------------------------------------

    @staticmethod
    def is_feeder(device: dict[str, Any]) -> bool:
        """True if device capabilities indicate a feeder (pet:N or pfp:1)."""
        cap_str = device.get("capability") or "{}"
        try:
            cap = json.loads(cap_str)
        except (TypeError, ValueError):
            return False
        caps = cap.get("caps", {}) or {}
        return bool(caps.get("pet")) or bool(caps.get("pfp"))

    async def list_feeders(self) -> list[dict[str, Any]]:
        """Return all camera devices with feeder capabilities."""
        resp = await self.get_device_list()
        out: list[dict[str, Any]] = []
        for bucket in ("ipc", "snap"):
            for d in resp.get(bucket, []) or []:
                if self.is_feeder(d):
                    out.append(d)
        return out
