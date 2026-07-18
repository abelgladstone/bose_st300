"""Locate the SoundTouch on the LAN via mDNS, with a configured-host fallback."""

from __future__ import annotations

import logging
import os
import socket
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

_LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_soundtouch._tcp.local."
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass
class Config:
    host: str | None = None
    name: str = ""
    server_host: str = "0.0.0.0"
    server_port: int = 5001

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        data = tomllib.loads(path.read_text()) if path.exists() else {}
        device = data.get("device", {})
        server = data.get("server", {})
        # Env vars win over config.toml so the container is configurable without a rebuild.
        return cls(
            host=os.environ.get("BOSE_HOST") or device.get("host") or None,
            name=os.environ.get("BOSE_NAME") or device.get("name", ""),
            server_host=server.get("host", "0.0.0.0"),
            server_port=int(server.get("port", 5001)),
        )


class _Listener(ServiceListener):
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=3000)
        if info and info.addresses:
            self.hosts.append(socket.inet_ntoa(info.addresses[0]))

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass


def discover(timeout: float = 5.0) -> str | None:
    """Return the first SoundTouch address found over mDNS, or None."""
    zc = Zeroconf()
    listener = _Listener()
    try:
        ServiceBrowser(zc, SERVICE_TYPE, listener)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not listener.hosts:
            time.sleep(0.1)
    finally:
        zc.close()
    return listener.hosts[0] if listener.hosts else None


def resolve_host(config: Config | None = None) -> str:
    config = config or Config.load()
    if config.host:
        return config.host
    _LOGGER.info("no host configured, discovering over mDNS...")
    host = discover()
    if not host:
        raise RuntimeError(
            "No SoundTouch found on the network and no host set in config.toml"
        )
    _LOGGER.info("discovered SoundTouch at %s", host)
    return host
