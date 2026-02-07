#!/usr/bin/env python3
"""Ghost Chat LLM Bot — connects Ollama to Ghost Chat.

Usage:
    python3 ghost_bot.py --host     # Create room, wait for browser
    python3 ghost_bot.py --join     # Join existing room
    python3 ghost_bot.py --demo     # Two bots chat (test)
"""
import asyncio, argparse, requests, json, sys
from ghost_client import GhostClient

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"

def ollama_chat(messages):
    """Get response from local Ollama."""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "messages": messages,
            "stream": False
        }, timeout=60)
        return r.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Error: {e}]"

async def host_mode():
    """Bot creates room, waits for browser to join."""
    client = GhostClient(nick="LLM")
    room_id, room_key, offer = await client.create_room()

    print(f"\n[+] Room created!")
    print(f"[+] Join code:\n{offer}\n")
    print("[+] Send this code to someone to chat.")

    answer = input("\n[?] Paste their answer code (A:...): ").strip()
    if not answer.startswith("A:"):
        print("[!] Invalid answer code")
        return

    await client.accept_answer(answer)
    await client.wait_connected()
    print("[+] Connected! LLM ready.\n")

    conversation = [{"role": "system", "content":
        "You are a helpful AI assistant. Keep responses brief (1-2 sentences)."}]

    try:
        while True:
            msg = await client.receive()
            if msg.type == "chat" and msg.from_id != client.my_id:
                print(f"[{msg.nick}] {msg.text}")
                conversation.append({"role": "user", "content": msg.text})
                reply = ollama_chat(conversation)
                conversation.append({"role": "assistant", "content": reply})
                print(f"[LLM] {reply}")
                await client.send(reply)
    except KeyboardInterrupt:
        pass
    finally:
        await client.close()

async def join_mode():
    """Bot joins a room created by browser."""
    code = input("[?] Paste G: code: ").strip()
    if not code.startswith("G:"):
        print("[!] Invalid code")
        return

    parts = code[2:].split(".")
    if len(parts) != 3:
        print("[!] Invalid code format")
        return

    room_id, room_key, offer_compressed = parts

    client = GhostClient(nick="LLM")
    await client.set_room(room_id, room_key)

    # Reconstruct offer code
    from ghost_client import decompress_sdp
    offer_sdp = decompress_sdp(offer_compressed)
    offer = "O:" + offer_compressed

    answer = await client.accept_offer(offer)

    print(f"\n[+] Answer code (give this back):\n{answer}\n")
    print("[+] Waiting for connection...")

    await client.wait_connected()
    print("[+] Connected! LLM ready.\n")

    conversation = [{"role": "system", "content":
        "You are a helpful AI assistant. Keep responses brief (1-2 sentences)."}]

    try:
        while True:
            msg = await client.receive()
            if msg.type == "chat" and msg.from_id != client.my_id:
                print(f"[{msg.nick}] {msg.text}")
                conversation.append({"role": "user", "content": msg.text})
                reply = ollama_chat(conversation)
                conversation.append({"role": "assistant", "content": reply})
                print(f"[LLM] {reply}")
                await client.send(reply)
    except KeyboardInterrupt:
        pass
    finally:
        await client.close()

async def demo():
    """Two bots chat with each other."""
    print("[demo] Creating room...")
    alice = GhostClient(nick="Alice")
    room_id, room_key, offer = await alice.create_room()

    bob = GhostClient(nick="LLM")
    await bob.set_room(room_id, room_key)
    answer = await bob.accept_offer(offer)
    await alice.accept_answer(answer)

    await alice.wait_connected()
    await bob.wait_connected()
    print("[demo] Connected!\n")

    await alice.send("Hello! Can you help me with something?")

    conversation = [{"role": "system", "content":
        "You are a helpful assistant. Be brief."}]

    for _ in range(3):
        msg = await bob.receive()
        if msg.type == "chat":
            print(f"  {msg.nick}: {msg.text}")
            conversation.append({"role": "user", "content": msg.text})
            reply = ollama_chat(conversation)
            conversation.append({"role": "assistant", "content": reply})
            print(f"  LLM: {reply}")
            await bob.send(reply)

            # Alice's turn
            msg2 = await alice.receive()
            if msg2.type == "chat":
                print(f"  {msg2.nick}: {msg2.text}")
                await alice.send("Interesting, tell me more.")

    await alice.close()
    await bob.close()
    print("\n[demo] Done.")

def main():
    p = argparse.ArgumentParser(description="Ghost Chat LLM Bridge")
    p.add_argument("--host", action="store_true", help="Create room, wait for peer")
    p.add_argument("--join", action="store_true", help="Join existing room")
    p.add_argument("--demo", action="store_true", help="Two bots demo")
    args = p.parse_args()

    if args.host:
        asyncio.run(host_mode())
    elif args.join:
        asyncio.run(join_mode())
    elif args.demo:
        asyncio.run(demo())
    else:
        print("Ghost Chat LLM Bridge")
        print("\nUsage:")
        print("  python3 ghost_bot.py --host    # Create room")
        print("  python3 ghost_bot.py --join    # Join room")
        print("  python3 ghost_bot.py --demo    # Test mode")
        print("\nMake sure Ollama is running: ollama run qwen2.5:3b")

if __name__ == "__main__":
    main()
