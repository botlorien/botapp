"""Controle de enquadramento (iframe) configurável e genérico.

Por padrão reproduz o comportamento do Django (X-Frame-Options a partir de
``settings.X_FRAME_OPTIONS``, default DENY) — instalações públicas não mudam.

Quando ``BOTAPP_FRAME_ANCESTORS`` está definido (lista separada por espaço/vírgula
de origens, ex.: "'self' https://portal.exemplo.com"), o middleware REMOVE o
X-Frame-Options (que não expressa origem específica) e publica um CSP
``frame-ancestors`` — permitindo embutir o dashboard só nas origens allowlistadas.
Substitui o ``django.middleware.clickjacking.XFrameOptionsMiddleware`` no MIDDLEWARE.
"""
import os

from django.conf import settings


def _ancestors():
    raw = os.getenv("BOTAPP_FRAME_ANCESTORS", "").strip()
    if not raw:
        return ""
    partes = [p for p in raw.replace(",", " ").split() if p]
    return " ".join(partes)


class FrameAncestorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ancestors = _ancestors()

    def __call__(self, request):
        response = self.get_response(request)
        if self.ancestors:
            # allowlist de enquadramento por origem → CSP; sem X-Frame-Options.
            response.headers.pop("X-Frame-Options", None)
            existente = response.headers.get("Content-Security-Policy", "")
            if "frame-ancestors" not in existente:
                diretiva = f"frame-ancestors {self.ancestors}"
                response.headers["Content-Security-Policy"] = (
                    f"{existente.rstrip('; ').strip()}; {diretiva}" if existente else diretiva
                )
        else:
            # comportamento padrão do Django (não sobrepõe se a view já setou).
            if "X-Frame-Options" not in response.headers and not getattr(
                response, "xframe_options_exempt", False
            ):
                response.headers["X-Frame-Options"] = getattr(settings, "X_FRAME_OPTIONS", "DENY")
        return response
