from typing_extensions import override

from radicalbit_ai_gateway.llm.embeddings import Embeddings


class MockWorkingEmbeddingModel(Embeddings):
    @override
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(i) for i in range(5)] for _ in texts]

    @override
    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @override
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class MockFailingEmbeddingModel(Embeddings):
    @override
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError('Embedding model failure')

    @override
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError('Embedding model failure')

    @override
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError('Embedding model failure')
