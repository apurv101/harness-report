#!/usr/bin/env python3
"""CooperBench's Redis inbox protocol, using only the Python standard library."""
import datetime
import json
import os
from pathlib import Path
import socket
import sys


def command(*parts):
    values = [str(part).encode() for part in parts]
    payload = b'*%d\r\n' % len(values) + b''.join(b'$%d\r\n' % len(v) + v + b'\r\n' for v in values)
    with socket.create_connection(('redis', 6379), timeout=10) as conn:
        conn.sendall(payload)
        stream = conn.makefile('rb')
        line = stream.readline()
        if line.startswith(b'-'):
            raise RuntimeError(line.decode().strip())
        if line.startswith(b'$'):
            size = int(line[1:])
            return None if size == -1 else stream.read(size).decode()
        if line.startswith(b':'):
            return int(line[1:])
        raise RuntimeError('Unexpected Redis response')


def main():
    sender = os.environ['AGENT_ID']
    if Path(sys.argv[0]).name == 'send_message':
        if len(sys.argv) < 3 or sys.argv[1] not in ('agent1', 'agent2'):
            raise SystemExit('Usage: send_message agent1|agent2 "message"')
        recipient = sys.argv[1]
        message = {'from': sender, 'to': recipient, 'content': ' '.join(sys.argv[2:]),
                   'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        command('RPUSH', recipient + ':inbox', json.dumps(message))
        print('Message sent to ' + recipient)
    else:
        found = False
        while (raw := command('LPOP', sender + ':inbox')) is not None:
            message = json.loads(raw)
            print(f"[Message from {message['from']}]: {message['content']}")
            found = True
        if not found:
            print('No new messages.')


if __name__ == '__main__':
    main()
