# botapp/rest_server.py

import threading
from wsgiref.simple_server import make_server
import os
import django

def start_rest_server(port=8888):
    def run():
        print(f"🔌 Iniciando servidor REST em http://127.0.0.1:{port}/api/")
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "botapp.settings")
        django.setup()
        from django.core.wsgi import get_wsgi_application
        app = get_wsgi_application()
        server = make_server("127.0.0.1", port, app)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    print("🔌 Servidor REST iniciado.")