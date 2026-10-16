import asyncio
import random

import httpx
import pytest

from app.services.bidding.transport import DSPTransport


async def _slow_http_server():
    """A real local HTTP server that answers each request after 20-150ms."""

    async def handle(reader, writer):
        try:
            while True:
                await reader.readuntil(b"\r\n\r\n")
                await asyncio.sleep(random.uniform(0.02, 0.15))
                writer.write(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok")
                await writer.drain()
        except Exception:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0, backlog=4096)


@pytest.mark.asyncio
async def test_burst_of_pool_timeouts_does_not_wedge_the_client():
    """A burst of short-timeout calls against a small pool makes httpcore hand
    fresh connections to requests whose pool timeout is firing. Without the
    transport's cleanup those slots stay CONNECTING forever and every later
    call times out; with it, the pool is usable again once the burst ends."""
    random.seed(3)
    server = await _slow_http_server()
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
    transport = DSPTransport(limits=httpx.Limits(max_connections=10))
    # The server is closed without waiting for its handlers, which would
    # block on keep-alive connections the burst abandoned.
    try:
        async with httpx.AsyncClient(transport=transport) as client:

            async def call():
                try:
                    await client.get(url, timeout=httpx.Timeout(0.1))
                except httpx.TimeoutException:
                    pass

            tasks = []
            for _ in range(1500):
                tasks.append(asyncio.create_task(call()))
                await asyncio.sleep(random.uniform(0, 0.002))
            await asyncio.gather(*tasks)

            stuck = [c for c in transport._pool.connections if c.info() == "CONNECTING"]
            assert stuck == []
            response = await client.get(url, timeout=httpx.Timeout(1.0))
            assert response.status_code == 200
    finally:
        server.close()
