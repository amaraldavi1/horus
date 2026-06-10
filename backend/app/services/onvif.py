"""ONVIF WS-Discovery and PTZ control.

The `onvif` package (onvif-zeep-async) is optional: PTZ endpoints return 501
when it is missing. WS-Discovery uses a raw UDP SOAP probe (stdlib only).
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

try:
    from onvif import ONVIFCamera  # type: ignore[import-untyped]

    ONVIF_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional package
    ONVIFCamera = None  # type: ignore[assignment]
    ONVIF_AVAILABLE = False

_MULTICAST_ADDR = ("239.255.255.250", 3702)

_PROBE_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
    ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header><w:MessageID>uuid:{message_id}</w:MessageID>"
    "<w:To e:mustUnderstand=\"true\">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
    "<w:Action e:mustUnderstand=\"true\">"
    "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>"
    "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
    "</e:Envelope>"
)

_XADDR_RE = re.compile(r"<[^>]*XAddrs[^>]*>([^<]+)<")
_SCOPES_RE = re.compile(r"<[^>]*Scopes[^>]*>([^<]+)<")


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.responses: list[tuple[str, str]] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.responses.append((addr[0], data.decode(errors="replace")))


def _scope_value(scopes: str, key: str) -> str | None:
    match = re.search(rf"onvif://www\.onvif\.org/{key}/([^\s]+)", scopes)
    if match:
        return match.group(1).replace("%20", " ")
    return None


async def discover(timeout: float = 3.0) -> list[dict]:
    """WS-Discovery probe; returns [{ip, name, xaddr, manufacturer}]."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.bind(("0.0.0.0", 0))

    transport, protocol = await loop.create_datagram_endpoint(_DiscoveryProtocol, sock=sock)
    try:
        probe = _PROBE_TEMPLATE.format(message_id=uuid.uuid4()).encode()
        transport.sendto(probe, _MULTICAST_ADDR)
        await asyncio.sleep(timeout)
    finally:
        transport.close()

    results: list[dict] = []
    seen: set[str] = set()
    for ip, body in protocol.responses:
        xaddr_match = _XADDR_RE.search(body)
        if not xaddr_match:
            continue
        xaddr = xaddr_match.group(1).split()[0]
        if xaddr in seen:
            continue
        seen.add(xaddr)
        scopes = _SCOPES_RE.search(body)
        scopes_text = scopes.group(1) if scopes else ""
        results.append(
            {
                "ip": ip,
                "name": _scope_value(scopes_text, "name"),
                "xaddr": xaddr,
                "manufacturer": _scope_value(scopes_text, "manufacturer")
                or _scope_value(scopes_text, "hardware"),
            }
        )
    return results


def _require_onvif() -> None:
    if not ONVIF_AVAILABLE:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail="ONVIF support unavailable: the 'onvif-zeep-async' package is not installed",
        )


async def ptz_command(
    main_url: str,
    username: str | None,
    password: str | None,
    *,
    action: str,
    pan: float = 0.0,
    tilt: float = 0.0,
    zoom: float = 0.0,
    preset: str | None = None,
) -> None:
    """Execute a PTZ action against the camera's ONVIF service."""
    _require_onvif()
    parts = urlsplit(main_url)
    host = parts.hostname
    if not host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Camera URL has no resolvable host")
    port = parts.port if parts.scheme.startswith("http") and parts.port else 80

    try:
        device = ONVIFCamera(host, port, username or "", password or "")
        await device.update_xaddrs()
        media = await device.create_media_service()
        ptz = await device.create_ptz_service()
        profiles = await media.GetProfiles()
        if not profiles:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Camera exposes no media profiles")
        token = profiles[0].token

        if action == "move":
            request = ptz.create_type("ContinuousMove")
            request.ProfileToken = token
            request.Velocity = {"PanTilt": {"x": pan, "y": tilt}, "Zoom": {"x": zoom}}
            await ptz.ContinuousMove(request)
        elif action == "stop":
            await ptz.Stop({"ProfileToken": token, "PanTilt": True, "Zoom": True})
        elif action == "preset":
            if preset is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="preset is required for action=preset")
            await ptz.GotoPreset({"ProfileToken": token, "PresetToken": preset})
        await device.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - zeep raises a wide variety of errors
        logger.warning("PTZ command failed for %s: %s", host, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"PTZ command failed: {exc}") from exc
