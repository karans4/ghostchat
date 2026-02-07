#!/usr/bin/env python3
"""Minimal WebSocket signaling server for Ghost Chat.
Memory target: <20MB RAM."""

import asyncio, json, sys
from collections import defaultdict

rooms = defaultdict(set)  # room_id -> set of websockets

async def handle(ws, path):
    """Handle one WebSocket connection."""
    room = path.split('?room=')[-1] if '?room=' in path else None
    if not room:
        await ws.close()
        return

    # Join room
    rooms[room].add(ws)
    peers = len(rooms[room])

    # Notify peer count
    await ws.send(json.dumps({'type': 'peers', 'count': peers}))

    # Notify others of join
    for peer in rooms[room]:
        if peer != ws:
            await peer.send(json.dumps({'type': 'join'}))

    try:
        async for msg in ws:
            # Relay to room
            for peer in rooms[room]:
                if peer != ws:
                    await peer.send(msg)
    finally:
        # Leave room
        rooms[room].discard(ws)
        if not rooms[room]:
            del rooms[room]
        else:
            for peer in rooms[room]:
                await peer.send(json.dumps({'type': 'leave'}))

async def main():
    import websockets
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    async with websockets.serve(handle, '0.0.0.0', port):
        print(f'Ghost signal server on ws://0.0.0.0:{port}')
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
