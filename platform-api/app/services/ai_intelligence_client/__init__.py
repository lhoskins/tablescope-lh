
from __future__ import annotations

from .endpoints import ask as ask
from .endpoints import classify_conversation_turn as classify_conversation_turn
from .endpoints import fix_sql as fix_sql
from .endpoints import generate_action_draft as generate_action_draft
from .endpoints import generate_sql as generate_sql
from .endpoints import interpret as interpret
from .endpoints import investigate_step as investigate_step
from .endpoints import knowledge_graph_cards as knowledge_graph_cards
from .endpoints import plan as plan
from .endpoints import project_insight as project_insight
from .endpoints import repair_sql_step as repair_sql_step
from .endpoints import search_grounding_vectors as search_grounding_vectors
from .endpoints import select_matching_insight_card as select_matching_insight_card
from .transport import _BUSY_DEFAULT_RETRY_SECONDS as _BUSY_DEFAULT_RETRY_SECONDS
from .transport import _BUSY_MAX_ATTEMPTS as _BUSY_MAX_ATTEMPTS
from .transport import _BUSY_MAX_RETRY_SECONDS as _BUSY_MAX_RETRY_SECONDS
from .transport import _CHAT_MAX_CONCURRENT as _CHAT_MAX_CONCURRENT
from .transport import _TIMEOUT as _TIMEOUT
from .transport import AIUnavailableError as AIUnavailableError
from .transport import _chat_sem as _chat_sem
from .transport import _chat_semaphore as _chat_semaphore
from .transport import _post as _post
from .transport import _retry_seconds as _retry_seconds
from .transport import _sign_payload as _sign_payload
from .transport import get_settings as get_settings
from .transport import is_enabled as is_enabled
from .transport import logger as logger

"""Signed client for the AI server's intelligence endpoints.

Wraps the HMAC-signed POST to ``/ai/intelligence/plan`` and
``/ai/intelligence/interpret``. Kept separate from the route layer so the
home-intelligence service can drive the plan -> execute -> interpret loop
without importing route modules (avoids circular imports).

Disabled AI returns ``None`` so callers can degrade cleanly. Transport, timeout,
HTTP, and malformed-response failures raise :class:`AIUnavailableError` so
streaming callers can report an honest error instead of a misleading empty result.
"""
