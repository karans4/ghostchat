#!/usr/bin/env node
// Minimal WebSocket signaling server for Ghost Chat
// Runs on your server as backup to Cloudflare/Fly

const WebSocket = require('ws');
const http = require('http');
const https = require('https');
const fs = require('fs');

const PORT = process.env.PORT || 8443;
const USE_HTTPS = process.env.USE_HTTPS === 'true';

// In-memory room storage
const rooms = new Map();

function createServer() {
  if (USE_HTTPS) {
    // For production with proper certs
    const key = fs.readFileSync(process.env.SSL_KEY || '/etc/ssl/private/key.pem');
    const cert = fs.readFileSync(process.env.SSL_CERT || '/etc/ssl/certs/cert.pem');
    return https.createServer({ key, cert });
  }
  return http.createServer();
}

const server = createServer();
const wss = new WebSocket.Server({ server, path: '/' });

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const roomId = url.searchParams.get('room');

  if (!roomId) {
    ws.close(1008, 'Missing room');
    return;
  }

  // Join room
  if (!rooms.has(roomId)) {
    rooms.set(roomId, new Set());
  }
  const room = rooms.get(roomId);
  room.add(ws);

  console.log(`[${roomId}] peer joined (${room.size} total)`);

  // Send peer count
  ws.send(JSON.stringify({ type: 'peers', count: room.size }));

  // Notify others
  for (const peer of room) {
    if (peer !== ws && peer.readyState === WebSocket.OPEN) {
      peer.send(JSON.stringify({ type: 'join' }));
    }
  }

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data);
      // Relay to others in room
      for (const peer of room) {
        if (peer !== ws && peer.readyState === WebSocket.OPEN) {
          peer.send(JSON.stringify(msg));
        }
      }
    } catch (e) {
      // Invalid message
    }
  });

  ws.on('close', () => {
    room.delete(ws);
    console.log(`[${roomId}] peer left (${room.size} remaining)`);
    if (room.size === 0) {
      rooms.delete(roomId);
    } else {
      for (const peer of room) {
        if (peer.readyState === WebSocket.OPEN) {
          peer.send(JSON.stringify({ type: 'leave' }));
        }
      }
    }
  });

  ws.on('error', (err) => {
    console.error(`[${roomId}] error:`, err.message);
  });
});

server.listen(PORT, () => {
  console.log(`Ghost signal server on port ${PORT}`);
  console.log(`WebSocket URL: ws${USE_HTTPS ? 's' : ''}://localhost:${PORT}/?room=TEST`);
});
