"""One way to write a JSON file another process or thread may read while it is written.

`Path.write_text` truncates the file first, so a reader that opens it between the truncate and the write sees an empty
or half-written file. `write_json` writes a temp file in the same directory and `os.replace`s it over the target, so a
reader sees the old complete file or the new complete file. Stdlib only.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json(path: str | Path, data: Any) -> None:
    target = Path(path)
    # Same directory as the target: os.replace is atomic only within one filesystem.
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
