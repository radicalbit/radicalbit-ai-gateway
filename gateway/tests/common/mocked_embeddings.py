class MockWorkingEmbeddingModel:
    @staticmethod
    async def aembed_documents(texts: list[str]):
        return [[float(i) for i in range(5)] for _ in texts]


class MockFailingEmbeddingModel:
    @staticmethod
    async def aembed_documents(texts: list[str]):
        raise RuntimeError('Embedding model failure')
