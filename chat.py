import asyncio
import socket
import argparse
from typing import Dict, Tuple, Set
import logging


class Chat:
    def __init__(self, name: str, ip: str, port: int, broadcast_port: int):
        self.name = name
        self.ip = ip
        self.port = port
        self.broadcast_port = broadcast_port
        self.peers: Dict[Tuple[str, int], asyncio.StreamWriter] = {}
        self.known_peers: Set[Tuple[str, int]] = set()
        self.lock = asyncio.Lock()
        self.running = True
        self.logger = self._setup_logger()

        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.udp_socket.bind(('0.0.0.0', broadcast_port))
        except OSError as e:
            self.logger.warning(f"Failed to bind to broadcast port {broadcast_port}: {e}")
            self.udp_socket.bind(('0.0.0.0', 0))
            self.broadcast_port = self.udp_socket.getsockname()[1]
            self.logger.info(f"Using random broadcast port: {self.broadcast_port}")
        self.udp_socket.setblocking(False)

    def _setup_logger(self):
        logger = logging.getLogger('p2p_chat')
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    async def discovery_service(self):
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                self.udp_socket.sendto(
                    f"{self.name}@{self.ip}:{self.port}".encode(),
                    ('<broadcast>', self.broadcast_port)
                )

                try:
                    data, addr = await loop.sock_recvfrom(self.udp_socket, 1024)
                    if addr[0] != self.ip:
                        message = data.decode()
                        self.logger.debug(f"Received discovery message: {message}")
                        await self.process_discovery(message)
                except (BlockingIOError, ConnectionResetError) as e:
                    self.logger.debug(f"UDP receive error: {e}")
                    pass

                await asyncio.sleep(3)
            except Exception as e:
                self.logger.error(f"Discovery service error: {e}")
                await asyncio.sleep(3)

    async def process_discovery(self, message: str):
        try:
            if '@' not in message:
                return

            peer_name, peer_addr = message.split('@')
            peer_ip, peer_port_str = peer_addr.split(':')
            peer_port = int(peer_port_str)

            if peer_name == self.name:
                return

            peer_key = (peer_ip, peer_port)

            async with self.lock:
                if peer_key not in self.known_peers:
                    self.known_peers.add(peer_key)
                    self.logger.info(f"Discovered new peer: {peer_name} at {peer_ip}:{peer_port}")

            await self.connect_to_peer(peer_ip, peer_port, peer_name)
        except ValueError as e:
            self.logger.warning(f"Invalid discovery message format: {message} - {e}")

    async def connection_service(self):
        server = await asyncio.start_server(
            self.handle_connection,
            self.ip,
            self.port,
            reuse_address=True,
            backlog=10
        )
        async with server:
            await server.serve_forever()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer_addr = writer.get_extra_info('peername')
        peer_key = (peer_addr[0], peer_addr[1])
        peer_name = "Unknown"

        try:
            peer_name = (await reader.read(1024)).decode().strip()

            if peer_name == self.name:
                writer.close()
                await writer.wait_closed()
                return

            async with self.lock:
                if peer_key in self.peers:
                    old_writer = self.peers[peer_key]
                    if not old_writer.is_closing():
                        old_writer.close()
                        await old_writer.wait_closed()
                self.peers[peer_key] = writer
                self.known_peers.add(peer_key)

            while self.running:
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=30.0)
                    if not data:
                        break

                    message = data.decode().strip()
                    if not message:
                        continue

                    if ":" in message:
                        sender, text = message.split(":", 1)
                        print(f"\n{sender.strip()}: {text.strip()}\n> ", end="", flush=True)
                    else:
                        print(f"\n{peer_name}: {message}\n> ", end="", flush=True)
                    await self.forward_message(peer_key, message)
                except asyncio.TimeoutError:
                    try:
                        writer.write(b'\n')
                        await writer.drain()
                    except Exception:
                        break
                    continue
                except Exception as e:
                    self.logger.warning(f"Connection error with {peer_name}: {e}")
                    break
        except Exception as e:
            self.logger.error(f"Error handling connection: {e}")
        finally:
            async with self.lock:
                if peer_key in self.peers:
                    writer.close()
                    await writer.wait_closed()
                    del self.peers[peer_key]

    async def forward_message(self, sender_key: Tuple[str, int], message: str):
        if ":" not in message or message.startswith(f"{self.name}:"):
            return

        first_colon = message.find(":")
        original_sender = message[:first_colon].strip()
        original_text = message[first_colon + 1:].strip()

        async with self.lock:
            disconnected_peers = []
            for peer_key, writer in self.peers.items():
                if peer_key != sender_key:
                    try:
                        if not writer.is_closing():
                            writer.write(f"{original_sender}:{original_text}\n".encode())
                            await writer.drain()
                    except Exception as e:
                        self.logger.warning(f"Failed to forward message to {peer_key}: {e}")
                        disconnected_peers.append(peer_key)

            for peer_key in disconnected_peers:
                if peer_key in self.peers:
                    writer = self.peers[peer_key]
                    if not writer.is_closing():
                        writer.close()
                        await writer.wait_closed()
                    del self.peers[peer_key]

    async def connect_to_peer(self, ip: str, port: int, name: str):
        if ip == self.ip and port == self.port:
            return

        peer_key = (ip, port)

        async with self.lock:
            if peer_key in self.peers:
                return

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )

            writer.write(self.name.encode())
            await writer.drain()

            async with self.lock:
                self.peers[peer_key] = writer
                self.known_peers.add(peer_key)

            asyncio.create_task(self.handle_connection(reader, writer))
        except asyncio.TimeoutError:
            self.logger.warning(f"Connection timeout to {name} at {ip}:{port}")
        except Exception as e:
            self.logger.warning(f"Failed to connect to {name} at {ip}:{port}: {str(e)}")

    async def send_message(self, message: str):
        if not message.strip():
            return

        full_message = f"{self.name}: {message.strip()}"
        print(f"You: {message.strip()}")

        async with self.lock:
            disconnected_peers = []
            for peer_key, writer in self.peers.items():
                try:
                    if not writer.is_closing():
                        writer.write(full_message.encode())
                        await writer.drain()
                except Exception as e:
                    self.logger.warning(f"Failed to send message to {peer_key}: {e}")
                    disconnected_peers.append(peer_key)

            for peer_key in disconnected_peers:
                if peer_key in self.peers:
                    writer = self.peers[peer_key]
                    if not writer.is_closing():
                        writer.close()
                        await writer.wait_closed()
                    del self.peers[peer_key]

    async def input_handler(self):
        while self.running:
            try:
                message = await asyncio.get_event_loop().run_in_executor(
                    None,
                    input,
                    "> "
                )
                if not self.running:
                    break

                if message.lower() == '/exit':
                    self.running = False
                    break
                elif message.lower() == '/peers':
                    async with self.lock:
                        print("\nConnected peers:")
                        for peer in self.peers:
                            print(f"- {peer[0]}:{peer[1]}")
                        print("> ", end="", flush=True)
                    continue

                await self.send_message(message)
            except (EOFError, KeyboardInterrupt):
                self.running = False
                break
            except Exception as e:
                self.logger.error(f"Input handler error: {e}")
                continue

    async def run(self):
        self.logger.info(f"Starting P2P chat as {self.name} on {self.ip}:{self.port}")

        tasks = [
            asyncio.create_task(self.discovery_service()),
            asyncio.create_task(self.connection_service()),
            asyncio.create_task(self.input_handler())
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")
        finally:
            self.running = False
            async with self.lock:
                for writer in self.peers.values():
                    if not writer.is_closing():
                        writer.close()
                        await writer.wait_closed()
            self.udp_socket.close()
            self.logger.info("Chat service stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Async P2P Chat')
    parser.add_argument('--name', required=True, help='Your name')
    parser.add_argument('--ip', required=True, help='Your IP address')
    parser.add_argument('--port', type=int, required=True, help='TCP port')
    parser.add_argument('--broadcast-port', type=int, default=37020,
                        help='UDP broadcast port (default: 37020)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    chat = Chat(args.name, args.ip, args.port, args.broadcast_port)
    if args.debug:
        chat.logger.setLevel(logging.DEBUG)

    try:
        asyncio.run(chat.run())
    except KeyboardInterrupt:
        print("\nExiting...")