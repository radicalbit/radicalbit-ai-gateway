"""Prompt templates rendered with ``str.format`` semantics."""

from dataclasses import dataclass
from string import Formatter


@dataclass(frozen=True)
class PromptTemplate:
    """A ``{variable}`` template.

    Every brace pair is a placeholder: a literal brace must be doubled, and an
    unknown placeholder raises ``KeyError`` when formatting.
    """

    template: str
    input_variables: list[str]

    def format(self, **kwargs: str) -> str:
        return Formatter().format(self.template, **kwargs)
