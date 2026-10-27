from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
from collections.abc import Iterable

AllowedNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
DEFAULT_ALLOWED_CLIENT_CIDRS = ("127.0.0.0/8", "::1/128")


def parse_allowed_client_cidrs(values: Iterable[str]) -> tuple[AllowedNetwork, ...]:
    networks: list[AllowedNetwork] = []
    for raw_value in values:
        for candidate in str(raw_value or "").split(","):
            normalized = candidate.strip()
            if normalized:
                networks.append(ipaddress.ip_network(normalized, strict=False))
    if not networks:
        networks = [
            ipaddress.ip_network(value) for value in DEFAULT_ALLOWED_CLIENT_CIDRS
        ]
    return tuple(networks)


def client_ip_allowed(
    peername: object,
    allowed_networks: Iterable[AllowedNetwork],
) -> bool:
    if not isinstance(peername, tuple) or not peername:
        return False
    try:
        address = ipaddress.ip_address(str(peername[0]).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(
        address.version == network.version and address in network
        for network in allowed_networks
    )


def rewrite_http_host_header(header: bytes, upstream_authority: str) -> bytes:
    """Rewrite only the initial HTTP Host header accepted by Chromium DevTools."""
    lines = header.split(b"\r\n")
    replacement = f"Host: {upstream_authority}".encode("ascii")
    for index, line in enumerate(lines):
        if line.lower().startswith(b"host:"):
            lines[index] = replacement
            break
    return b"\r\n".join(lines)


def close_http_response_header(header: bytes) -> bytes:
    """A one-request Host relay must not advertise a reusable HTTP connection."""
    lines = header.split(b"\r\n")
    preserved = [
        line
        for line in lines[1:]
        if line
        and line.partition(b":")[0].lower() not in {b"connection", b"keep-alive"}
    ]
    return b"\r\n".join([lines[0], *preserved, b"Connection: close", b"", b""])


async def copy_http_response(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    # Preserve framing and payload bytes; only the final HTTP header changes.
    # Chromium can keep a socket open even when its request says close.
    while True:
        try:
            header = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            return
        status = header.split(b"\r\n", 1)[0].split()[1:2]
        interim = bool(status and status[0].isdigit() and 100 <= int(status[0]) < 200)
        upgraded = status == [b"101"]
        writer.write(header if interim else close_http_response_header(header))
        await writer.drain()
        if not interim or upgraded:
            break
    await copy_stream(reader, writer)


async def copy_stream(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass


async def relay_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    upstream_host: str,
    upstream_port: int,
    allowed_networks: tuple[AllowedNetwork, ...],
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    tasks: set[asyncio.Task[None]] = set()
    try:
        if not client_ip_allowed(
            client_writer.get_extra_info("peername"),
            allowed_networks,
        ):
            return
        try:
            header = await client_reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError as error:
            header = error.partial
        if not header:
            return

        upstream_reader, upstream_writer = await asyncio.open_connection(
            upstream_host,
            upstream_port,
        )
        authority = f"{upstream_host}:{upstream_port}"
        upstream_writer.write(rewrite_http_host_header(header, authority))
        await upstream_writer.drain()

        upgrade = any(
            line.partition(b":")[0].lower() == b"upgrade"
            for line in header.split(b"\r\n")[1:]
        )
        copy_response = copy_stream if upgrade else copy_http_response
        tasks = {
            asyncio.create_task(copy_stream(client_reader, upstream_writer)),
            asyncio.create_task(copy_response(upstream_reader, client_writer)),
        }
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except (ConnectionError, asyncio.LimitOverrunError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        client_writer.close()
        with contextlib.suppress(Exception):
            await client_writer.wait_closed()
        if upstream_writer is not None:
            upstream_writer.close()
            with contextlib.suppress(Exception):
                await upstream_writer.wait_closed()


async def serve(
    *,
    listen_host: str,
    listen_port: int,
    upstream_host: str,
    upstream_port: int,
    allowed_networks: tuple[AllowedNetwork, ...],
) -> None:
    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await relay_connection(
            reader,
            writer,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            allowed_networks=allowed_networks,
        )

    server = await asyncio.start_server(handle, listen_host, listen_port)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chromium CDP Host-header relay")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=9223)
    parser.add_argument(
        "--allow-cidr",
        action="append",
        default=[],
        help="Client CIDR allowed to use the relay; repeat for multiple networks.",
    )
    args = parser.parse_args()
    allowed_networks = parse_allowed_client_cidrs(args.allow_cidr)
    asyncio.run(
        serve(
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            upstream_host=args.upstream_host,
            upstream_port=args.upstream_port,
            allowed_networks=allowed_networks,
        )
    )


if __name__ == "__main__":
    main()
