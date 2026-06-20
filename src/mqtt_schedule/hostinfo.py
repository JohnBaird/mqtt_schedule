from __future__ import annotations

from dataclasses import dataclass
from random import getrandbits
from socket import AF_INET, SOCK_DGRAM, gethostname, socket
from uuid import uuid4


@dataclass(frozen=True)
class HostIdentity:
    host_name: str
    ip_address: str
    session_client_id: str


class HostInfoProvider:
    def get_identity(self) -> HostIdentity:
        host_name = gethostname()
        ip_address = self._get_primary_ip_address()
        session_client_id = self._make_session_client_id()
        return HostIdentity(
            host_name=host_name,
            ip_address=ip_address,
            session_client_id=session_client_id,
        )

    @staticmethod
    def _get_primary_ip_address() -> str:
        sock = socket(AF_INET, SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
        except OSError:
            return ""
        finally:
            sock.close()

    @staticmethod
    def _make_session_client_id() -> str:
        mac_hex = uuid4().hex[:12]
        mac_dec = str(int(mac_hex, 16))
        random_number = getrandbits(16)
        return f"{mac_dec}{random_number}"
