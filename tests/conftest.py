"""Point the app at a throwaway download directory before it is imported."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="pull1sec-tests-"))
os.environ.setdefault("PULL1SEC_DOWNLOAD_DIR", str(_TMP / "downloads"))
os.environ.setdefault("PULL1SEC_ALLOW_PRIVATE_HOSTS", "true")
