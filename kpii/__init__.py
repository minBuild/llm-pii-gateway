"""kpii — 한국어 PII 탐지·마스킹 코어 (LiteLLM 무의존).

LiteLLM/FastAPI 를 import 하지 않는다 (DESIGN §9-7). 게이트웨이 어댑터는 litellm/ 에 둔다.
"""

from .engine import merge, plan, scan
from .masking import MaskingSession, StreamRestorer
from .policy import NerConfig, Policy
from .types import Action, Detection

__version__ = "0.1.0"

__all__ = [
    "Action",
    "Detection",
    "MaskingSession",
    "NerConfig",
    "Policy",
    "StreamRestorer",
    "merge",
    "plan",
    "scan",
    "__version__",
]
