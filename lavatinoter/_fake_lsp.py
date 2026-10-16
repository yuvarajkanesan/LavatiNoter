"""A tiny stand-in language server used by the self-test (it answers initialize, definition and hover and reports a diagnostic
for every line that contains BAD). Not used by the application itself."""
import json
import sys


def read():
    headers = b""
    while not headers.endswith(b"\r\n\r\n"):
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        headers += ch
    n = int([l for l in headers.split(b"\r\n") if l.lower().startswith(b"content-length")][0].split(b":")[1])
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))


def send(msg):
    body = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()


docs = {}
while True:
    m = read()
    if m is None:
        break
    method = m.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": m["id"], "result": {"capabilities": {"definitionProvider": True, "hoverProvider": True}}})
    elif method in ("textDocument/didOpen", "textDocument/didChange"):
        td = m["params"]["textDocument"]
        text = td.get("text") if method.endswith("didOpen") else m["params"]["contentChanges"][0]["text"]
        docs[td["uri"]] = text
        diags = [{"range": {"start": {"line": i, "character": line.index("BAD")}, "end": {"line": i, "character": line.index("BAD") + 3}},
                  "severity": 1, "message": "found BAD"} for i, line in enumerate(text.split("\n")) if "BAD" in line]
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": td["uri"], "diagnostics": diags}})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": m["id"], "result": [{"uri": m["params"]["textDocument"]["uri"],
                                                          "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 9}}}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": m["id"], "result": {"contents": {"kind": "markdown", "value": "**fake** hover"}}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": m["id"], "result": None})
    elif method == "exit":
        break
