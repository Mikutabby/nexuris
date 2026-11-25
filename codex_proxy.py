"""Proxy mínimo: OpenAI Responses/Chat -> sesión Nexuris en opencode."""
import json, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path.home() / "nexuris"))
from nexuris.core.opencode_backend import OpenCodeClient, ensure_available

ensure_available()
client = OpenCodeClient()
sid = client.create_session(title="Codex -> Nexuris")

def get_text(payload):
    inp = payload.get("input", payload.get("prompt", ""))
    if isinstance(inp, str):
        return inp
    if isinstance(inp, list):
        out = []
        for item in inp:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                c = item.get("content")
                if isinstance(c, str):
                    out.append(c)
                elif isinstance(c, list):
                    for p in c:
                        if isinstance(p, dict) and p.get("type") in ("input_text", "text"):
                            out.append(p.get("text", ""))
        return "\n".join(out)
    return ""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, body, code=200):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_event(self, obj):
        self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode())

    def do_GET(self):
        if self.path.startswith("/v1/models") or self.path.startswith("/models"):
            self.send_json({"object": "list", "data": [{"id": "nexuris", "object": "model", "owned_by": "nexuris"}]})
        elif "health" in self.path:
            self.send_json({"ok": True, "session": sid})
        else:
            self.send_json({"error": {"message": "not found"}}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self.send_json({"error": {"message": "bad json"}}, 400)
            return
        text = get_text(payload)
        try:
            reply = client.run_turn(sid, text)
        except Exception as exc:
            self.send_json({"error": {"message": str(exc)[:400], "type": "server_error"}}, 502)
            return

        if self.path.startswith("/v1/chat/completions"):
            self.send_json({
                "id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion", "model": "nexuris",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
            return

        rid = "resp_" + uuid.uuid4().hex[:24]
        iid = "msg_" + uuid.uuid4().hex[:16]
        item = {"type": "message", "id": iid, "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": reply, "annotations": []}]}
        response = {"id": rid, "object": "response", "status": "completed", "model": "nexuris",
                    "output": [item], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}

        if not payload.get("stream"):
            self.send_json(response)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.send_event({"type": "response.created", "response": {**response, "status": "in_progress"}})
            self.send_event({"type": "response.in_progress", "response": {**response, "status": "in_progress"}})
            self.send_event({"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress"}})
            self.send_event({"type": "response.content_part.added", "item_id": iid, "output_index": 0,
                             "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})
            chunk = 80
            for i in range(0, len(reply), chunk):
                self.send_event({"type": "response.output_text.delta", "item_id": iid, "output_index": 0,
                                 "content_index": 0, "delta": reply[i:i+chunk]})
            self.send_event({"type": "response.output_text.done", "item_id": iid, "output_index": 0,
                             "content_index": 0, "text": reply})
            self.send_event({"type": "response.content_part.done", "item_id": iid, "output_index": 0,
                             "content_index": 0, "part": {"type": "output_text", "text": reply, "annotations": []}})
            self.send_event({"type": "response.output_item.done", "output_index": 0, "item": item})
            self.send_event({"type": "response.completed", "response": response})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

ThreadingHTTPServer(("127.0.0.1", 4205), Handler).serve_forever()
