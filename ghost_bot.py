#!/usr/bin/env python3
"""Ghost Chat LLM Bot — headless agent that joins a room and chats via Ollama.

Two modes:
  1. Two headless bots talk to each other (demo/test):
     python3 ghost_bot.py --demo

  2. Bot creates a room, prints offer code, you paste into browser:
     python3 ghost_bot.py --host

  3. Bot joins an existing room (paste the offer code):
     python3 ghost_bot.py --join
"""
import asyncio, argparse, sys, requests, json
from ghost_client import GhostClient

def ollama(model, messages):
    r = requests.post('http://localhost:11434/api/chat', json={
        'model': model, 'messages': messages, 'stream': False
    }, timeout=120)
    r.raise_for_status()
    return r.json()['message']['content'].strip()

async def demo(model):
    """Two headless agents chat with each other. One uses Ollama, one is scripted."""
    print('[demo] Creating room...')
    alice = GhostClient(nick='alice')
    room_id, room_key, offer = await alice.create_room()
    print(f'[demo] Room {room_id} created')

    bob = GhostClient(nick='ghost-llm')
    await bob.set_room(room_id, room_key)
    answer = await bob.accept_offer(offer)
    await alice.accept_answer(answer)

    print('[demo] Connecting...')
    for _ in range(20):
        await asyncio.sleep(0.5)
        if alice.connected and bob.connected:
            break
    if not (alice.connected and bob.connected):
        print('[demo] FAILED to connect')
        await alice.close(); await bob.close()
        return
    print('[demo] Connected!\n')

    await alice.send('hey, are you there?')

    conversation = [{'role': 'system', 'content':
        'You are ghost-llm, an AI agent in an encrypted P2P chat. '
        'Keep responses to 1-2 sentences. Be casual.'}]

    followups = [
        'cool, what can you do?',
        'tell me something interesting',
        'what do you think about P2P systems?',
        'thanks, gotta go. bye!'
    ]

    for i in range(5):
        msg = await bob.receive(timeout=10)
        if msg.type != 'chat': continue
        print(f'  {msg.nick}: {msg.text}')

        conversation.append({'role': 'user', 'content': msg.text})
        reply = ollama(model, conversation).split('\n')[0].strip()
        conversation.append({'role': 'assistant', 'content': reply})
        print(f'  ghost-llm: {reply}')
        await bob.send(reply)

        if i < len(followups):
            await asyncio.sleep(0.5)
            await alice.receive(timeout=10)  # drain bob's reply from alice's queue
            await alice.send(followups[i])

    await alice.close()
    await bob.close()
    print('\n[demo] Done.')

async def host_mode(model, nick):
    """Bot creates a room and waits for a browser peer."""
    client = GhostClient(nick=nick)
    room_id, room_key, offer = await client.create_room()
    print(f'\nRoom: {room_id}')
    print(f'Room URL fragment: #{client.room_url_fragment}')
    print(f'\n--- YOUR CONNECTION CODE (copy this to the browser) ---')
    print(offer)
    print('--- END CODE ---\n')

    answer = input('Paste the browser\'s response code (A:...): ').strip()
    await client.accept_answer(answer)
    print('Connecting...')
    await client.wait_connected()
    print('Connected! Bot is chatting.\n')

    conversation = [{'role': 'system', 'content':
        f'You are {nick}, an AI agent in Ghost Chat. Short, casual responses.'}]

    try:
        while True:
            msg = await client.receive(timeout=300)
            if msg.type == 'chat' and msg.from_id != client.my_id:
                print(f'[{msg.nick}] {msg.text}')
                conversation.append({'role': 'user', 'content': msg.text})
                reply = ollama(model, conversation)
                reply = reply.split('\n')[0]
                conversation.append({'role': 'assistant', 'content': reply})
                print(f'[{nick}] {reply}')
                await client.send(reply)
    except (KeyboardInterrupt, asyncio.TimeoutError):
        pass
    finally:
        await client.close()

async def join_mode(model, nick):
    """Bot joins an existing room from a browser host."""
    room_id = input('Room ID: ').strip()
    room_key = input('Room key (base64url): ').strip()
    offer = input('Paste offer code (O:...): ').strip()

    client = GhostClient(nick=nick)
    await client.set_room(room_id, room_key)
    answer = await client.accept_offer(offer)
    print(f'\n--- YOUR RESPONSE CODE (paste in browser) ---')
    print(answer)
    print('--- END CODE ---\n')

    input('Press Enter after pasting in browser...')
    await client.wait_connected()
    print('Connected!\n')

    conversation = [{'role': 'system', 'content':
        f'You are {nick}, an AI agent in Ghost Chat. Short, casual responses.'}]

    try:
        while True:
            msg = await client.receive(timeout=300)
            if msg.type == 'chat' and msg.from_id != client.my_id:
                print(f'[{msg.nick}] {msg.text}')
                conversation.append({'role': 'user', 'content': msg.text})
                reply = ollama(model, conversation)
                reply = reply.split('\n')[0]
                conversation.append({'role': 'assistant', 'content': reply})
                print(f'[{nick}] {reply}')
                await client.send(reply)
    except (KeyboardInterrupt, asyncio.TimeoutError):
        pass
    finally:
        await client.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--demo', action='store_true', help='Two headless bots demo')
    p.add_argument('--host', action='store_true', help='Bot creates room, waits for browser peer')
    p.add_argument('--join', action='store_true', help='Bot joins existing room')
    p.add_argument('--model', default='qwen2.5:3b')
    p.add_argument('--nick', default='ghost-llm')
    args = p.parse_args()

    if args.demo:
        asyncio.run(demo(args.model))
    elif args.host:
        asyncio.run(host_mode(args.model, args.nick))
    elif args.join:
        asyncio.run(join_mode(args.model, args.nick))
    else:
        print('Usage: ghost_bot.py --demo | --host | --join')
        print('  --demo: Two headless bots chat (tests everything)')
        print('  --host: Bot creates room for browser peer')
        print('  --join: Bot joins browser peer\'s room')

if __name__ == '__main__':
    main()
