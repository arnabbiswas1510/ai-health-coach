import http.server
import urllib.request
import urllib.error
import subprocess
import sys
import os
import time
from dotenv import load_dotenv

load_dotenv()


class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Always serve files from the data directory
        base_dir = os.path.join(os.getcwd(), 'data')
        # SimpleHTTPRequestHandler serves from cwd, so translate path relative to 'data'
        path = super().translate_path(path)
        rel_path = os.path.relpath(path, os.getcwd())
        return os.path.join(base_dir, rel_path)

    def do_POST(self):
        if self.path.startswith('/api/'):
            self.proxy_request()
        else:
            super().do_POST()

    def do_GET(self):
        if self.path.startswith('/api/'):
            self.proxy_request()
        else:
            super().do_GET()

    def do_DELETE(self):
        if self.path.startswith('/api/'):
            self.proxy_request()
        else:
            super().do_DELETE()

    def proxy_request(self):
        # Forward request to uvicorn on 8001 (stripping /api prefix)
        target_path = self.path[4:] if self.path.startswith('/api/') else self.path
        url = f"http://127.0.0.1:8001{target_path}"
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Build clean headers
        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ('host', 'content-length'):
                headers[k] = v

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=self.command
        )

        try:
            with urllib.request.urlopen(req) as response:
                self.send_response(response.status)
                for k, v in response.getheaders():
                    # Avoid duplicate or conflicting transfer headers
                    if k.lower() not in ('transfer-encoding', 'content-length'):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding', 'content-length'):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

def run_static_server():
    server_address = ('', 8085)
    httpd = http.server.HTTPServer(server_address, ProxyHTTPRequestHandler)
    print("\n" + "="*70)
    print("  Garmin AI Coach - Local Dev Server Started!")
    print("  Dashboard: http://localhost:8085/index.html")
    print("  API Proxy: http://localhost:8085/api/ -> http://localhost:8001/")
    print("="*70 + "\n")
    httpd.serve_forever()

if __name__ == '__main__':
    # Start uvicorn in a separate process
    print("Starting Chat API (uvicorn) on port 8001...")
    env = os.environ.copy()
    env["OUTPUT_DIR"] = os.path.join(os.getcwd(), "data")
    
    uvicorn_process = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "services.chat_api.main:app",
        "--host", "127.0.0.1", "--port", "8001"
    ], env=env)
    
    # Wait for uvicorn to start
    time.sleep(2)
    
    try:
        run_static_server()
    except KeyboardInterrupt:
        print("\nStopping local servers...")
        uvicorn_process.terminate()
