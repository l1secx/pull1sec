"""Point the app at throwaway directories before it is imported."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="pull1sec-tests-"))

os.environ.setdefault("PULL1SEC_DOWNLOAD_DIR", str(_TMP / "downloads"))
os.environ.setdefault("PULL1SEC_STATE_DIR", str(_TMP / "state"))
os.environ.setdefault("PULL1SEC_ALLOW_PRIVATE_HOSTS", "true")
# Tests bind to loopback, but be explicit so the auth gate is what is tested.
os.environ.setdefault("PULL1SEC_HOST", "127.0.0.1")
