"""The SDK of this repository (``sdk/``), importable by the gateway's tests.

Loaded from its sources rather than installed: a dev dependency on ``../sdk``
would put the SDK's requirements in the gateway's lock, and the image build
resolves that lock with only ``gateway/`` at hand. The SDK needs nothing the
gateway does not already have (httpx2, pydantic, typing-extensions).
"""

from pathlib import Path
import sys

_SDK_SOURCES = Path(__file__).resolve().parents[3] / 'sdk' / 'src'
sys.path.insert(0, str(_SDK_SOURCES))
