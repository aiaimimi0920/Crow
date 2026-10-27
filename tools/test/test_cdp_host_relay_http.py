"""Loopback-only HTTP reuse and upgraded-stream contracts for the CDP relay."""

import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace

import pytest
import requests

from tools import cdp_host_relay as relay


@asynccontextmanager
async def running_relay(upstream_handler):
    tasks = set()
    writers = set()

    async def tracked(handler, reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.add(writer)
        try:
            await handler(reader, writer)
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            writers.discard(writer)
            tasks.discard(task)

    upstream = await asyncio.start_server(
        lambda r, w: tracked(upstream_handler, r, w), "127.0.0.1", 0
    )
    port = upstream.sockets[0].getsockname()[1]

    async def handle(reader, writer):
        await relay.relay_connection(
            reader,
            writer,
            upstream_host="127.0.0.1",
            upstream_port=port,
            allowed_networks=relay.parse_allowed_client_cidrs([]),
        )

    server = await asyncio.start_server(
        lambda r, w: tracked(handle, r, w), "127.0.0.1", 0
    )
    try:
        yield server.sockets[0].getsockname()[1], port
    finally:
        server.close()
        upstream.close()
        await server.wait_closed()
        await upstream.wait_closed()
        for writer in tuple(writers):
            writer.close()
        for task in tuple(tasks):
            task.cancel()
        await asyncio.gather(*tuple(tasks), return_exceptions=True)


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("interim", [False, True])
def test_http_session_reuse_never_forwards_an_unrewritten_host(chunked, interim):
    async def scenario():
        connections = []
        closed_connections = []
        all_closed = asyncio.Event()
        body = b'[{"type":"page"}]'

        async def upstream(reader, writer):
            connections.append(writer)
            while True:
                try:
                    header = await reader.readuntil(b"\r\n\r\n")
                except asyncio.IncompleteReadError:
                    closed_connections.append(writer)
                    if len(closed_connections) == 2:
                        all_closed.set()
                    return
                allowed = f"Host: 127.0.0.1:{upstream_port}\r\n".encode()
                status = b"200 OK" if allowed in header else b"500 Invalid Host"
                if interim:
                    writer.write(b"HTTP/1.1 100 Continue\r\nX-Hint: fixture\r\n\r\n")
                framing = (
                    b"Transfer-Encoding: chunked\r\n"
                    if chunked
                    else f"Content-Length: {len(body)}\r\n".encode()
                )
                writer.write(
                    b"HTTP/1.1 " + status + b"\r\n"
                    b"Connection: keep-alive\r\nKeep-Alive: timeout=60\r\n"
                    b"Content-Type: application/json\r\n" + framing + b"\r\n"
                )
                await writer.drain()
                wire = (
                    f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
                    if chunked
                    else body
                )
                writer.write(wire)
                await writer.drain()

        def client(port):
            with requests.Session() as session:
                session.trust_env = False
                session.headers["Host"] = "pc2-browser-solver:9224"
                return [
                    session.get(f"http://127.0.0.1:{port}{path}", timeout=2)
                    for path in ("/json/version", "/json/list")
                ]

        async with running_relay(upstream) as (port, upstream_port):
            responses = await asyncio.to_thread(client, port)
            assert [r.status_code for r in responses] == [200, 200]
            assert [r.content for r in responses] == [body, body]
            assert all(r.headers["Connection"].lower() == "close" for r in responses)
            assert all("Keep-Alive" not in r.headers for r in responses)
            assert len(connections) == 2
            # Assert natural cleanup before the fixture's fallback cancellation.
            await asyncio.wait_for(all_closed.wait(), timeout=1)

    asyncio.run(scenario())


def test_websocket_upgrade_and_bidirectional_binary_stream_are_unchanged():
    async def scenario():
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Connection: Upgrade\r\nUpgrade: websocket\r\n"
            b"Sec-WebSocket-Accept: fixture\r\n\r\n"
        )
        frame = b"\x82\x10\x00\xff\r\n\r\nHost: binary"
        observed = []

        async def upstream(reader, writer):
            observed.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(response)
            await writer.drain()
            payload = await reader.readexactly(len(frame))
            writer.write(payload)
            await writer.drain()
            await reader.read()

        async with running_relay(upstream) as (port, upstream_port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write(
                    b"GET /devtools/browser/fixture HTTP/1.1\r\n"
                    b"Host: pc2-browser-solver:9224\r\n"
                    b"cOnNeCtIoN: keep-alive, UpGrAdE\r\n"
                    b"uPgRaDe: WebSocket\r\n\r\n"
                )
                await writer.drain()
                assert await reader.readuntil(b"\r\n\r\n") == response
                writer.write(frame)
                await writer.drain()
                assert await reader.readexactly(len(frame)) == frame
                assert f"Host: 127.0.0.1:{upstream_port}\r\n".encode() in observed[0]
                assert b"cOnNeCtIoN: keep-alive, UpGrAdE\r\n" in observed[0]
            finally:
                writer.close()
                await writer.wait_closed()

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("connection", [b"", b"cOnNeCtIoN: keep-alive\r\n"])
def test_response_header_close_keeps_framing_and_other_headers(connection):
    header = (
        b"HTTP/1.1 200 OK\r\n"
        + connection
        + b"kEeP-aLiVe: timeout=60\r\nContent-Length: 123\r\n"
        b"Content-Type: application/json\r\nX-Receipt: fixture\r\n\r\n"
    )
    assert relay.close_http_response_header(header) == (
        b"HTTP/1.1 200 OK\r\nContent-Length: 123\r\n"
        b"Content-Type: application/json\r\nX-Receipt: fixture\r\n"
        b"Connection: close\r\n\r\n"
    )


@pytest.mark.parametrize("status", [b"100 Continue", b"103 Early Hints"])
def test_informational_headers_and_coalesced_binary_body_are_preserved(status):
    async def scenario():
        interim = b"HTTP/1.1 " + status + b"\r\nX-Hint: fixture\r\n\r\n"
        final = b"HTTP/1.1 200 OK\r\nContent-Length: 18\r\n\r\n"
        body = b"\x00\xff\r\nConnection: x\r\n"
        reader = asyncio.StreamReader()
        reader.feed_data(interim + final + body)
        reader.feed_eof()
        output = []

        async def drain():
            pass

        writer = SimpleNamespace(write=output.append, drain=drain)
        await relay.copy_http_response(reader, writer)
        assert (
            b"".join(output) == interim + relay.close_http_response_header(final) + body
        )

    asyncio.run(scenario())


def test_eof_delimited_response_keeps_the_complete_body():
    async def scenario():
        body = b"metadata-without-content-length\x00\xff"

        async def upstream(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\n\r\n" + body)
            await writer.drain()

        async with running_relay(upstream) as (port, _):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write(b"GET /json/version HTTP/1.1\r\nHost: fixture\r\n\r\n")
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), timeout=2)
                assert (
                    response == b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + body
                )
            finally:
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())
