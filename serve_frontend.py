import http.server
import socketserver
import os

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving files from {DIRECTORY}")
    print(f"Server started at http://localhost:{PORT}")
    print(f" - ETM Sample:   http://localhost:{PORT}/ETM%20Sample.html")
    print(f" - Citycoders:   http://localhost:{PORT}/citycoders.html")
    print("Press Ctrl+C to stop the server.")
    httpd.serve_forever()
