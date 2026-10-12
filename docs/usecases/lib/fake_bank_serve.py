"""Runs the fake bank (fake_bank_https) for a Node ui use case: prints one JSON line with what tools-service needs to
reach it (its settings, the private range to list, the host), then serves until stdin closes or it is signalled."""

from __future__ import annotations

import json
import sys

from fake_bank_https import HOST, fake_bank

with fake_bank() as bank:
    print(json.dumps({"settings": bank.settings, "range": bank.range, "host": HOST}), flush=True)
    # The harness holds stdin open; it closes when the harness stops this process or exits.
    sys.stdin.read()
