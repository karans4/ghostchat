// Minimal WebSocket signaling server for Ghost Chat
// Build: go build -o signal signal.go
// Usage: ./signal [-port 8443] [-cert cert.pem] [-key key.pem]

package main

import (
	"flag"
	"log"
	"net/http"
	"strings"
	"sync"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

type Room struct {
	mu     sync.RWMutex
	peers  map[*websocket.Conn]bool
}

var (
	rooms = make(map[string]*Room)
	roomsMu sync.RWMutex
)

func getRoom(id string) *Room {
	roomsMu.Lock()
	defer roomsMu.Unlock()
	if r, ok := rooms[id]; ok {
		return r
	}
	r := &Room{peers: make(map[*websocket.Conn]bool)}
	rooms[id] = r
	return r
}

func (r *Room) join(ws *websocket.Conn) {
	r.mu.Lock()
	r.peers[ws] = true
	count := len(r.peers)
	r.mu.Unlock()

	// Send peer count to new peer
	ws.WriteJSON(map[string]interface{}{"type": "peers", "count": count})

	// Notify others
	r.broadcast(ws, map[string]string{"type": "join"})
}

func (r *Room) leave(ws *websocket.Conn) {
	r.mu.Lock()
	delete(r.peers, ws)
	empty := len(r.peers) == 0
	r.mu.Unlock()

	if empty {
		roomsMu.Lock()
		delete(rooms, r)
		roomsMu.Unlock()
	} else {
		r.broadcast(ws, map[string]string{"type": "leave"})
	}
}

func (r *Room) broadcast(from *websocket.Conn, msg interface{}) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for peer := range r.peers {
		if peer != from {
			peer.WriteJSON(msg)
		}
	}
}

func handleWS(w http.ResponseWriter, r *http.Request) {
	roomID := r.URL.Query().Get("room")
	if roomID == "" {
		http.Error(w, "Missing room", http.StatusBadRequest)
		return
	}

	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer ws.Close()

	room := getRoom(roomID)
	room.join(ws)
	defer room.leave(ws)

	for {
		var msg map[string]interface{}
		if err := ws.ReadJSON(&msg); err != nil {
			break
		}
		room.broadcast(ws, msg)
	}
}

func main() {
	port := flag.String("port", "8080", "Port to listen on")
	cert := flag.String("cert", "", "TLS certificate file")
	key := flag.String("key", "", "TLS key file")
	flag.Parse()

	http.HandleFunc("/", handleWS)

	addr := ":" + *port
	log.Printf("Ghost signal server on %s", addr)

	if *cert != "" && *key != "" {
		log.Fatal(http.ListenAndServeTLS(addr, *cert, *key, nil))
	} else {
		log.Printf("Warning: Running without TLS")
		log.Fatal(http.ListenAndServe(addr, nil))
	}
}
