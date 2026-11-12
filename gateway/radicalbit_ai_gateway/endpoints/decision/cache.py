"""How a decision request is cached."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from radicalbit_ai_gateway.caching.route_cache import ExactEntry, Hit


@dataclass(frozen=True)
class DecisionEntry(ExactEntry):
    """A decision request, keyed on its (screened) state and questions and
    on the model that answers it.
    """

    state: Any
    questions: Any
    model_id: str

    hit_log = 'Decision cache hit. Key: %s'

    def signature(self) -> str:
        # Canonical JSON: sorted keys, so key order never changes the key.
        return json.dumps(
            {
                'state': self.state,
                'questions': self.questions,
                'model_id': self.model_id,
            },
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        )

    def parse(self, raw: str) -> dict:
        return json.loads(raw)

    def dump(self, value: dict) -> str:
        return json.dumps(value)

    def hit(self, value: dict) -> Hit:
        # A hit costs nothing: its input tokens are reported at $0.
        return Hit(value['model_id'], free_input_tokens=value['input_tokens'])
