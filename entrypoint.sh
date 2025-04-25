#!/bin/bash
set -e

# Inicia o servidor Gunicorn
echo "Iniciando servidor Botapp Dashboard..."
exec gunicorn botapp.wsgi:application --bind 0.0.0.0:8000 --workers 3
