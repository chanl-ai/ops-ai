"""A DNS server for tests and the dev stack that answers TXT queries from a dict, so a domain's proof record can be
published by a test (`PUT /dns/txt/{domain}` on the fake identity provider) and read by the service's real resolver
over UDP. Any other query, or a domain with no values, gets an empty answer."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass, field

import dns.message
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.rrset


@dataclass
class FakeDns:
    records: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    def answer(self, wire: bytes) -> bytes:
        query = dns.message.from_wire(wire)
        response = dns.message.make_response(query)
        for q in query.question:
            name = q.name.to_text(omit_final_dot=True).lower()
            values = self.records.get(name)
            if q.rdtype != dns.rdatatype.TXT or values is None:
                if values is None:
                    response.set_rcode(dns.rcode.NXDOMAIN)
                continue
            quoted = ['"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values]
            response.answer.append(dns.rrset.from_text_list(q.name, 60, dns.rdataclass.IN, dns.rdatatype.TXT, quoted))
        return response.to_wire()

    def serve(self, port: int = 0) -> tuple[int, threading.Event]:
        """Answers on 127.0.0.1 UDP `port` (0 picks one) in a daemon thread; returns the port and an event that stops
        it when set."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", port))
        sock.settimeout(0.2)
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                try:
                    wire, peer = sock.recvfrom(4096)
                except TimeoutError:
                    continue
                try:
                    sock.sendto(self.answer(wire), peer)
                except Exception:
                    continue
            sock.close()

        threading.Thread(target=loop, name="fake-dns", daemon=True).start()
        return int(sock.getsockname()[1]), stop
