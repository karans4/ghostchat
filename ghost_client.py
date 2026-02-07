"""Headless Ghost Chat client — no browser needed.

Speaks the same WebRTC + AES-256-GCM protocol as ghost.html.
Designed for LLM agents: simple connect/send/receive API.

Usage:
    # As offerer (create room):
    client = GhostClient(nick="bot")
    room_id, room_key, offer_code = await client.create_room()
    # give offer_code to peer, get answer_code back
    await client.accept_answer(answer_code)

    # As answerer (join room):
    client = GhostClient(nick="bot")
    await client.set_room(room_id, room_key)
    answer_code = await client.accept_offer(offer_code)
    # give answer_code back to offerer

    # Chat:
    await client.send("hello")
    msg = await client.receive()  # blocks until message arrives
"""
import asyncio, json, os, base64, zlib, uuid, time
from dataclasses import dataclass, field
from typing import Optional
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============ CRYPTO ============

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def b64url_decode(s: str) -> bytes:
    s += '=' * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)

def generate_room_key() -> bytes:
    """Generate a 256-bit AES key."""
    return AESGCM.generate_key(256)

def encrypt_message(key: bytes, plaintext: str) -> str:
    """AES-256-GCM encrypt. Returns base64url(iv + ciphertext)."""
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ct = aesgcm.encrypt(iv, plaintext.encode(), None)
    return b64url_encode(iv + ct)

def decrypt_message(key: bytes, data: str) -> str:
    """AES-256-GCM decrypt from base64url(iv + ciphertext)."""
    raw = b64url_decode(data)
    iv, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, None).decode()

# ============ SDP COMPRESS ============
# Compatible with browser's CompressionStream('deflate')

def compress_sdp(sdp: str) -> str:
    compressed = zlib.compress(sdp.encode())
    # Browser uses raw deflate, zlib adds header. Strip zlib header (2 bytes) and checksum (4 bytes).
    # Actually, CompressionStream('deflate') uses raw deflate with zlib wrapper.
    # Let's match it exactly: zlib.compress produces zlib format which is what 'deflate' means in web APIs.
    return b64url_encode(compressed)

def decompress_sdp(data: str) -> str:
    raw = b64url_decode(data)
    return zlib.decompress(raw).decode()

# ============ CLIENT ============

@dataclass
class Message:
    id: str
    type: str  # 'chat', 'sys', 'file-offer', etc.
    from_id: str = ''
    nick: str = ''
    text: str = ''
    ts: float = 0

class GhostClient:
    def __init__(self, nick: str = 'ghost-agent'):
        self.nick = nick
        self.my_id = str(uuid.uuid4())
        self.room_id: Optional[str] = None
        self.room_key: Optional[bytes] = None
        self.pc: Optional[RTCPeerConnection] = None
        self.dc = None  # data channel
        self._msg_queue: asyncio.Queue = asyncio.Queue()
        self._connected = asyncio.Event()
        self._peers: dict = {}

    def _create_pc(self):
        config = RTCConfiguration(iceServers=[
            RTCIceServer(urls=['stun:stun.l.google.com:19302'])
        ])
        self.pc = RTCPeerConnection(config)

    def _setup_dc(self, channel):
        self.dc = channel

        def do_open():
            self._connected.set()
            msg = {'type': 'join', 'peerId': self.my_id, 'nick': self.nick}
            asyncio.ensure_future(self._send_raw(msg))

        @channel.on('open')
        def on_open():
            do_open()

        @channel.on('message')
        def on_message(data):
            asyncio.ensure_future(self._handle_raw(data))

        @channel.on('close')
        def on_close():
            self._connected.clear()

        # If channel is already open (answerer case), fire immediately
        if hasattr(channel, 'readyState') and channel.readyState == 'open':
            do_open()

    async def _send_raw(self, msg: dict):
        if self.dc and self.dc.readyState == 'open':
            encrypted = encrypt_message(self.room_key, json.dumps(msg))
            self.dc.send(encrypted)

    async def _handle_raw(self, data):
        try:
            plaintext = decrypt_message(self.room_key, data)
            msg = json.loads(plaintext)
            msg_type = msg.get('type', '')

            if msg_type == 'chat':
                await self._msg_queue.put(Message(
                    id=msg.get('id', ''),
                    type='chat',
                    from_id=msg.get('from', ''),
                    nick=msg.get('nick', '?'),
                    text=msg.get('text', ''),
                    ts=msg.get('ts', 0)
                ))
            elif msg_type == 'join':
                await self._msg_queue.put(Message(
                    id=str(uuid.uuid4()),
                    type='sys',
                    nick=msg.get('nick', '?'),
                    text=f"{msg.get('nick', '?')} joined",
                    ts=time.time() * 1000
                ))
            elif msg_type == 'sync':
                for m in msg.get('messages', []):
                    if m.get('type') == 'chat':
                        await self._msg_queue.put(Message(
                            id=m.get('id', ''), type='chat',
                            from_id=m.get('from', ''), nick=m.get('nick', '?'),
                            text=m.get('text', ''), ts=m.get('ts', 0)
                        ))
            elif msg_type == 'destroy':
                await self._msg_queue.put(Message(
                    id=str(uuid.uuid4()), type='sys',
                    text='Room destroyed by admin', ts=time.time() * 1000
                ))
        except Exception as e:
            print(f'[ghost_client] decrypt/parse error: {e}')

    # ============ PUBLIC API ============

    async def create_room(self) -> tuple[str, str, str]:
        """Create a room. Returns (room_id, room_key_b64, offer_code)."""
        self.room_id = os.urandom(4).hex()
        self.room_key = generate_room_key()
        key_b64 = b64url_encode(self.room_key)

        self._create_pc()
        channel = self.pc.createDataChannel('ghost', ordered=True)
        self._setup_dc(channel)

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Wait for ICE gathering
        await self._wait_ice()

        code = 'O:' + compress_sdp(self.pc.localDescription.sdp)
        return self.room_id, key_b64, code

    async def set_room(self, room_id: str, room_key_b64: str):
        """Set room credentials for joining."""
        self.room_id = room_id
        self.room_key = b64url_decode(room_key_b64)

    async def accept_offer(self, offer_code: str) -> str:
        """Accept an offer, return answer code."""
        assert offer_code.startswith('O:'), 'Expected offer code (O:...)'
        sdp = decompress_sdp(offer_code[2:])

        self._create_pc()

        @self.pc.on('datachannel')
        def on_dc(channel):
            self._setup_dc(channel)

        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type='offer'))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        await self._wait_ice()

        return 'A:' + compress_sdp(self.pc.localDescription.sdp)

    async def accept_answer(self, answer_code: str):
        """Complete connection by accepting an answer."""
        assert answer_code.startswith('A:'), 'Expected answer code (A:...)'
        sdp = decompress_sdp(answer_code[2:])
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type='answer'))

    async def wait_connected(self, timeout: float = 15.0):
        """Wait for the data channel to open."""
        await asyncio.wait_for(self._connected.wait(), timeout)

    async def send(self, text: str):
        """Send a chat message."""
        msg = {
            'id': str(uuid.uuid4()),
            'type': 'chat',
            'from': self.my_id,
            'nick': self.nick,
            'text': text,
            'ts': time.time() * 1000
        }
        await self._send_raw(msg)

    async def receive(self, timeout: float = None) -> Message:
        """Receive next message. Blocks until one arrives."""
        if timeout:
            return await asyncio.wait_for(self._msg_queue.get(), timeout)
        return await self._msg_queue.get()

    def has_messages(self) -> bool:
        return not self._msg_queue.empty()

    async def close(self):
        if self.pc:
            await self.pc.close()

    async def _wait_ice(self, timeout=5.0):
        """Wait for ICE gathering to complete."""
        if self.pc.iceGatheringState == 'complete':
            return
        done = asyncio.Event()
        @self.pc.on('icegatheringstatechange')
        def check():
            if self.pc.iceGatheringState == 'complete':
                done.set()
        try:
            await asyncio.wait_for(done.wait(), timeout)
        except asyncio.TimeoutError:
            pass  # use whatever candidates we have

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def _add_debug_hooks(self):
        @self.pc.on('connectionstatechange')
        def on_conn():
            print(f'[ghost_client] connection: {self.pc.connectionState}')
        @self.pc.on('iceconnectionstatechange')
        def on_ice():
            print(f'[ghost_client] ice: {self.pc.iceConnectionState}')
        @self.pc.on('icegatheringstatechange')
        def on_gather():
            print(f'[ghost_client] gathering: {self.pc.iceGatheringState}')

    @property
    def room_url_fragment(self) -> str:
        """Return the #fragment for sharing."""
        return f'{self.room_id}.{b64url_encode(self.room_key)}'
