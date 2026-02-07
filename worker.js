// Cloudflare Worker: WebRTC Signaling Relay
// Matches peers by room ID, relays SDP offers/answers

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const roomId = url.searchParams.get('room');

    if (!roomId) {
      return new Response('Missing room param', { status: 400 });
    }

    // CORS headers
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: cors });
    }

    // WebSocket upgrade for signaling
    if (request.headers.get('Upgrade') === 'websocket') {
      return handleWebSocket(request, env, roomId, cors);
    }

    // Health check
    return new Response('Ghost Signaling Relay', { headers: cors });
  }
};

async function handleWebSocket(request, env, roomId, cors) {
  const [client, server] = Object.values(new WebSocketPair());

  // Get or create room
  const rooms = env.rooms || new Map();
  env.rooms = rooms;

  if (!rooms.has(roomId)) {
    rooms.set(roomId, new Set());
  }
  const room = rooms.get(roomId);

  server.accept();
  room.add(server);

  // Send peer count
  server.send(JSON.stringify({ type: 'peers', count: room.size }));

  // Broadcast join to others
  for (const peer of room) {
    if (peer !== server && peer.readyState === WebSocket.READY_STATE_OPEN) {
      peer.send(JSON.stringify({ type: 'join' }));
    }
  }

  server.addEventListener('message', (event) => {
    try {
      const msg = JSON.parse(event.data);
      msg.from = 'peer'; // anonymize

      // Relay to other peers in room
      for (const peer of room) {
        if (peer !== server && peer.readyState === WebSocket.READY_STATE_OPEN) {
          peer.send(JSON.stringify(msg));
        }
      }
    } catch (e) {
      // Invalid message, ignore
    }
  });

  server.addEventListener('close', () => {
    room.delete(server);
    if (room.size === 0) {
      rooms.delete(roomId);
    } else {
      // Notify others of leave
      for (const peer of room) {
        if (peer.readyState === WebSocket.READY_STATE_OPEN) {
          peer.send(JSON.stringify({ type: 'leave' }));
        }
      }
    }
  });

  return new Response(null, {
    status: 101,
    webSocket: client,
    headers: cors,
  });
}
