#!/usr/bin/env python3
"""Shell access to a task's declared streamable HTTP MCP servers.

Usage: hr-mcp SERVER list | hr-mcp SERVER call TOOL '{"argument": "value"}'
"""
import json
from pathlib import Path
import sys
import urllib.request


class Client:
    def __init__(self, url):
        self.url = url
        self.headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        self.sequence = 0

    def request(self, method, params, notification=False):
        self.sequence += 1
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            payload['id'] = self.sequence
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=self.headers)
        with urllib.request.urlopen(req, timeout=600) as response:
            if response.headers.get('Mcp-Session-Id'):
                self.headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
            if notification:
                return None
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                data = []
                for raw in response:
                    line = raw.decode().rstrip('\r\n')
                    if line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        result = json.loads('\n'.join(data)); data = []
                        if result.get('id') == self.sequence:
                            break
                else:
                    raise RuntimeError('MCP stream ended without a response')
            else:
                result = json.load(response)
        if 'error' in result:
            raise RuntimeError(json.dumps(result['error']))
        return result['result']

    def initialize(self):
        result = self.request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                              'clientInfo': {'name': 'harness-report-shell', 'version': '1.0'}})
        self.headers['MCP-Protocol-Version'] = result['protocolVersion']
        self.request('notifications/initialized', {}, notification=True)


def main():
    servers = json.loads(Path('/tmp/hr-mcp-servers.json').read_text())
    if len(sys.argv) < 3:
        raise SystemExit(__doc__ + '\nServers: ' + ', '.join(s['name'] for s in servers))
    server = next(s for s in servers if s['name'] == sys.argv[1])
    client = Client(server['url']); client.initialize()
    if sys.argv[2] == 'list':
        result = client.request('tools/list', {})
        tools = result['tools']
        while result.get('nextCursor'):
            result = client.request('tools/list', {'cursor': result['nextCursor']})
            tools.extend(result['tools'])
        print(json.dumps({'tools': tools}, indent=2))
    elif sys.argv[2] == 'call' and len(sys.argv) in (4, 5):
        result = client.request('tools/call', {'name': sys.argv[3], 'arguments': json.loads(sys.argv[4]) if len(sys.argv) == 5 else {}})
        print(json.dumps(result, indent=2))
        if result.get('isError'):
            raise SystemExit(1)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
