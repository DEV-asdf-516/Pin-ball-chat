import httpx

from util.singleton import Singleton


class HttpClient(Singleton):
    # 모든 provider가 공유하는 httpx.AsyncClient 싱글턴. connection pool을 재사용해 매 요청마다 새 커넥션을 맺지 않는다.

    _client: httpx.AsyncClient | None = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
