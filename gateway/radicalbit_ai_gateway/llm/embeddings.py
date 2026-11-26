"""Embedding model interface implemented by every embedding provider."""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable
import contextvars
import functools
from typing import TypeVar, TypeVarTuple

R = TypeVar('R')
Ts = TypeVarTuple('Ts')


class Embeddings(ABC):
    """Turns text into vectors.

    Providers implement the sync methods; the async ones default to running the
    sync ones in the default executor and are overridden by native async
    clients.
    """

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents to be searched over."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await _run_in_executor(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await _run_in_executor(self.embed_query, text)


async def _run_in_executor(func: Callable[[*Ts], R], *args: *Ts) -> R:
    # Carry the caller's context variables into the worker thread.
    ctx = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        None, functools.partial(ctx.run, func, *args)
    )
