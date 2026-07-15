"""Blocking HTTP client for the router admin panel.

This is the same login/parsing logic from the standalone script, packaged so
it can be called from Home Assistant's device_tracker platform. All methods
here are blocking (use `requests`) and must be called via
`hass.async_add_executor_job(...)`, never awaited directly.
"""
from __future__ import annotations

import base64
import re
import logging

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)

USER_DEVICE_FIELDS = [
    "Domain", "IpAddr", "MacAddr", "Port", "IpType",
    "DevType", "DevStatus", "PortType", "Time", "HostName",
]

_LINE_RE = re.compile(r"^\s*var UserDevinfo = new Array\(")
_DEVICE_CALL_RE = re.compile(r"new USERDevice\(([^)]*)\)")
_QUOTED_ARG_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
_HEX_ESCAPE_RE = re.compile(r"\\x([0-9a-fA-F]{2})")


def _decode_js_hex_escapes(value: str) -> str:
    return _HEX_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), value)


def parse_lan_user_dev_info(html: str) -> list[dict]:
    target_line = None
    for line in html.splitlines():
        if _LINE_RE.match(line):
            target_line = line
            break

    if target_line is None:
        return []

    devices = []
    for call_match in _DEVICE_CALL_RE.finditer(target_line):
        args_str = call_match.group(1)
        args = [_decode_js_hex_escapes(a) for a in _QUOTED_ARG_RE.findall(args_str)]
        devices.append(dict(zip(USER_DEVICE_FIELDS, args)))
    return devices


class RouterClient:
    """Handles login + fetching the connected-clients list for one router."""

    def __init__(self, host: str, username: str, password: str, timeout: int = 10) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._timeout = timeout
        self._session = requests.Session()
        self._session.verify = False
        self._session.headers.update({
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.9"
            ),
            "Connection": "keep-alive",
            "Origin": f"https://{host}",
            "Referer": f"https://{host}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
            ),
        })

    def _get_session_token(self) -> str:
        url = f"https://{self._host}/asp/GetRandCount.asp"
        resp = self._session.post(url, data="", timeout=self._timeout)
        resp.raise_for_status()
        token = resp.text.strip().lstrip("\ufeff").strip()
        if not token:
            raise RuntimeError("Empty token returned from GetRandCount.asp")
        return token

    def _login(self, token: str) -> None:
        url = f"https://{self._host}/login.cgi"
        payload = {
            "UserName": self._username,
            "PassWord": base64.b64encode(self._password.encode()).decode(),
            "Language": "english",
            "x.X_HW_Token": token,
        }
        resp = self._session.post(url, data=payload, timeout=self._timeout)
        resp.raise_for_status()

        if "CookieHttps" not in self._session.cookies.get_dict():
            raise RuntimeError(
                "Login did not set 'CookieHttps' cookie -- check credentials/token. "
                f"Response status={resp.status_code}"
            )

    def _get_lan_clients_raw(self) -> str:
        url = f"https://{self._host}/html/bbsp/common/GetLanUserDevInfo.asp"
        resp = self._session.post(url, data="", timeout=self._timeout)
        resp.raise_for_status()
        return resp.text

    def get_devices(self) -> list[dict]:
        """Full flow: token -> login -> fetch -> parse. Returns list of device dicts.

        Re-logs in on every call for simplicity/robustness (the router's
        session is short-lived anyway). If this proves too slow/chatty,
        session/cookie reuse with a re-login-on-401 fallback can be added.
        """
        token = self._get_session_token()
        self._login(token)
        raw_html = self._get_lan_clients_raw()
        return parse_lan_user_dev_info(raw_html)
