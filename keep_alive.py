import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Centro Comando HD - Bot Activo")

def run():
    # Render asigna un puerto dinámico, si falla usa 8080
    port = int(os.environ.get('PORT', 8080))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, handler)
    httpd.serve_forever()

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()