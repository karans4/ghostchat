/* Minimal WebSocket signaling server for Ghost Chat
 * Single-threaded, epoll-based, ~100KB RAM usage
 * Build: gcc -O2 -o signal signal.c -lssl -lcrypto
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <openssl/ssl.h>
#include <openssl/err.h>

#define MAX_EVENTS 64
#define MAX_CLIENTS 256
#define BUF_SIZE 4096
#define WS_GUID "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

typedef struct {
    int fd;
    SSL *ssl;
    char room[32];
    char buf[BUF_SIZE];
    int len;
    int handshake;
} Client;

static Client clients[MAX_CLIENTS];
static int epoll_fd;
static SSL_CTX *ssl_ctx;

void die(const char *msg) {
    perror(msg);
    exit(1);
}

int set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

void base64_encode(const unsigned char *in, int in_len, char *out) {
    static const char b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    int i, j;
    for (i = j = 0; i < in_len; i += 3, j += 4) {
        int v = in[i] << 16;
        if (i + 1 < in_len) v |= in[i+1] << 8;
        if (i + 2 < in_len) v |= in[i+2];
        out[j] = b64[(v >> 18) & 0x3F];
        out[j+1] = b64[(v >> 12) & 0x3F];
        out[j+2] = (i + 1 < in_len) ? b64[(v >> 6) & 0x3F] : '=';
        out[j+3] = (i + 2 < in_len) ? b64[v & 0x3F] : '=';
    }
    out[j] = '\0';
}

void sha1(const char *input, unsigned char *output) {
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha1(), NULL);
    EVP_DigestUpdate(ctx, input, strlen(input));
    EVP_DigestFinal_ex(ctx, output, NULL);
    EVP_MD_CTX_free(ctx);
}

int do_ws_handshake(Client *c) {
    char *key_start = strstr(c->buf, "Sec-WebSocket-Key: ");
    if (!key_start) return -1;
    key_start += 19;
    char *key_end = strchr(key_start, '\r');
    if (!key_end) return -1;

    char key[64];
    int key_len = key_end - key_start;
    memcpy(key, key_start, key_len);
    key[key_len] = '\0';

    /* Find room param */
    char *room_start = strstr(c->buf, "GET /?room=");
    if (room_start) {
        room_start += 11;
        char *room_end = strchr(room_start, ' ');
        if (room_end) {
            int room_len = room_end - room_start;
            if (room_len < 31) {
                memcpy(c->room, room_start, room_len);
                c->room[room_len] = '\0';
            }
        }
    }

    char concat[128];
    snprintf(concat, sizeof(concat), "%s%s", key, WS_GUID);

    unsigned char hash[20];
    sha1(concat, hash);

    char accept[64];
    base64_encode(hash, 20, accept);

    char response[512];
    snprintf(response, sizeof(response),
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: %s\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n", accept);

    SSL_write(c->ssl, response, strlen(response));

    /* Send peer count */
    int peers = 0;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (clients[i].fd != -1 && strcmp(clients[i].room, c->room) == 0) {
            peers++;
        }
    }
    char msg[64];
    snprintf(msg, sizeof(msg), "{\"type\":\"peers\",\"count\":%d}", peers);

    /* WebSocket text frame */
    unsigned char frame[128];
    int msg_len = strlen(msg);
    frame[0] = 0x81; /* FIN + text opcode */
    frame[1] = msg_len;
    memcpy(frame + 2, msg, msg_len);
    SSL_write(c->ssl, frame, msg_len + 2);

    /* Notify others */
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (clients[i].fd != -1 && clients[i].ssl &&
            strcmp(clients[i].room, c->room) == 0 && &clients[i] != c) {
            unsigned char notify[32];
            char *nmsg = "{\"type\":\"join\"}";
            int nlen = strlen(nmsg);
            notify[0] = 0x81;
            notify[1] = nlen;
            memcpy(notify + 2, nmsg, nlen);
            SSL_write(clients[i].ssl, notify, nlen + 2);
        }
    }

    return 0;
}

void relay_ws_frame(Client *src, unsigned char *data, int len) {
    for (int i = 0; i < MAX_CLIENTS; i++) {
        Client *dst = &clients[i];
        if (dst->fd != -1 && dst->ssl && dst != src &&
            strcmp(dst->room, src->room) == 0) {
            SSL_write(dst->ssl, data, len);
        }
    }
}

void handle_client(int fd) {
    Client *c = NULL;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (clients[i].fd == fd) {
            c = &clients[i];
            break;
        }
    }
    if (!c) return;

    int n = SSL_read(c->ssl, c->buf + c->len, BUF_SIZE - c->len - 1);
    if (n <= 0) {
        int err = SSL_get_error(c->ssl, n);
        if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
            return;
        }
        /* Disconnect */
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, fd, NULL);
        SSL_free(c->ssl);
        close(fd);
        c->fd = -1;
        c->ssl = NULL;

        /* Notify others in room */
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (clients[i].fd != -1 && clients[i].ssl &&
                strcmp(clients[i].room, c->room) == 0) {
                unsigned char notify[32];
                char *nmsg = "{\"type\":\"leave\"}";
                int nlen = strlen(nmsg);
                notify[0] = 0x81;
                notify[1] = nlen;
                memcpy(notify + 2, nmsg, nlen);
                SSL_write(clients[i].ssl, notify, nlen + 2);
            }
        }
        return;
    }

    c->len += n;
    c->buf[c->len] = '\0';

    if (!c->handshake) {
        if (strstr(c->buf, "\r\n\r\n")) {
            if (do_ws_handshake(c) == 0) {
                c->handshake = 1;
                c->len = 0;
            }
        }
    } else {
        /* WebSocket frame - relay to room */
        if (c->len >= 2) {
            int payload_len = c->buf[1] & 0x7F;
            int header_len = 2;
            if (payload_len == 126) header_len = 4;
            else if (payload_len == 127) header_len = 10;

            int mask = (c->buf[1] & 0x80) ? 4 : 0;
            int total_len = header_len + mask + payload_len;

            if (c->len >= total_len) {
                /* Unmask if needed and relay */
                if (mask) {
                    unsigned char *mask_key = (unsigned char *)c->buf + header_len;
                    unsigned char *payload = (unsigned char *)c->buf + header_len + 4;
                    for (int i = 0; i < payload_len; i++) {
                        payload[i] ^= mask_key[i % 4];
                    }
                    /* Re-mask for each peer */
                    relay_ws_frame(c, (unsigned char *)c->buf, total_len);
                } else {
                    relay_ws_frame(c, (unsigned char *)c->buf, total_len);
                }
                c->len = 0;
            }
        }
    }
}

void accept_conn(int listen_fd) {
    struct sockaddr_in addr;
    socklen_t len = sizeof(addr);
    int fd = accept(listen_fd, (struct sockaddr *)&addr, &len);
    if (fd < 0) return;

    set_nonblocking(fd);

    /* Find slot */
    Client *c = NULL;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (clients[i].fd == -1) {
            c = &clients[i];
            break;
        }
    }
    if (!c) {
        close(fd);
        return;
    }

    c->fd = fd;
    c->len = 0;
    c->handshake = 0;
    c->room[0] = '\0';

    c->ssl = SSL_new(ssl_ctx);
    SSL_set_fd(c->ssl, fd);
    SSL_set_accept_state(c->ssl);

    struct epoll_event ev = { .events = EPOLLIN | EPOLLET, .data.fd = fd };
    epoll_ctl(epoll_fd, EPOLL_CTL_ADD, fd, &ev);
}

int main(int argc, char **argv) {
    int port = 8443;
    const char *cert = "/etc/ssl/certs/cert.pem";
    const char *key = "/etc/ssl/private/key.pem";

    if (argc > 1) port = atoi(argv[1]);
    if (argc > 2) cert = argv[2];
    if (argc > 3) key = argv[3];

    /* Init clients */
    for (int i = 0; i < MAX_CLIENTS; i++) {
        clients[i].fd = -1;
        clients[i].ssl = NULL;
    }

    /* SSL init */
    SSL_library_init();
    SSL_load_error_strings();
    ssl_ctx = SSL_CTX_new(TLS_server_method());

    if (SSL_CTX_use_certificate_file(ssl_ctx, cert, SSL_FILETYPE_PEM) <= 0 ||
        SSL_CTX_use_PrivateKey_file(ssl_ctx, key, SSL_FILETYPE_PEM) <= 0) {
        fprintf(stderr, "Failed to load certificates\n");
        return 1;
    }

    /* Listen socket */
    int listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr));
    listen(listen_fd, 16);
    set_nonblocking(listen_fd);

    /* Epoll */
    epoll_fd = epoll_create1(0);
    struct epoll_event ev = { .events = EPOLLIN, .data.fd = listen_fd };
    epoll_ctl(epoll_fd, EPOLL_CTL_ADD, listen_fd, &ev);

    printf("Ghost signal server on port %d\n", port);

    struct epoll_event events[MAX_EVENTS];

    while (1) {
        int n = epoll_wait(epoll_fd, events, MAX_EVENTS, -1);
        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == listen_fd) {
                accept_conn(listen_fd);
            } else {
                handle_client(events[i].data.fd);
            }
        }
    }

    return 0;
}
