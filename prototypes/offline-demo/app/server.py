"""无第三方依赖的本地 HTTP 演示服务；仅绑定回环地址。"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.domain import contact_decision, recommendations
from app.service import Service

ROOT = Path(__file__).resolve().parents[1]
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "application/javascript"),
          "/style.css": ("style.css", "text/css")}


def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, payload, content_type="application/json"):
            body = json.dumps(payload, ensure_ascii=False).encode() if content_type == "application/json" else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in STATIC:
                filename, mime = STATIC[path]
                return self.send(200, (ROOT / "web" / filename).read_bytes(), mime)
            endpoints = {
                "/api/health": lambda: {"status": "ok", "mode": "offline-demo"},
                "/api/overview": service.overview,
                "/api/profiles": lambda: [{**p, "recommendations": recommendations(p), "contact": contact_decision(p)} for p in service.profiles()],
                "/api/campaigns": service.campaigns, "/api/metrics": service.simulated_experiment,
                "/api/audit": service.audit,
            }
            if path not in endpoints:
                return self.send(404, {"error": "路径不存在"})
            return self.send(200, endpoints[path]())

        def do_POST(self):
            # 阻止跨站浏览器请求修改本地演示状态；这里不是企业身份认证。
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                return self.send(403, {"error": "仅允许本地同源请求"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "需要 application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    return self.send(413, {"error": "请求体为空或过大"})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求体必须是对象")
                path = urlsplit(self.path).path
                if path == "/api/campaigns":
                    pid = data.get("passenger_id")
                    if not isinstance(pid, str):
                        raise ValueError("passenger_id 必须为字符串")
                    return self.send(201, service.create_campaign(pid))
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "campaigns"] and parts[3] in ["approve", "simulate"]:
                    return self.send(200, service.transition(parts[2], parts[3]))
                return self.send(404, {"error": "路径不存在"})
            except (ValueError, UnicodeDecodeError) as exc:
                return self.send(400, {"error": str(exc)})

        def log_message(self, format, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", default=str(ROOT / "runtime" / "demo.sqlite3"))
    args = parser.parse_args()
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(Service(args.database)))
    print(f"航旅数字画像演示：http://127.0.0.1:{args.port}（合成数据，不发送消息）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
