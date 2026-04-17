# botapp/rest_server.py

import threading
import logging
from wsgiref.simple_server import make_server
import os
import django

logger = logging.getLogger(__name__)


def start_rest_server(port=8888):
    def run():
        logger.info("Iniciando servidor REST em http://127.0.0.1:%s/api/", port)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "botapp.settings")
        django.setup()
        from django.core.wsgi import get_wsgi_application
        app = get_wsgi_application()
        server = make_server("127.0.0.1", port, app)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    logger.info("Servidor REST iniciado em thread daemon")