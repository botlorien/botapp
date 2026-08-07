"""SSO de entrada por One-Time Token (OTT) assinado com HMAC-SHA256.

Recurso GENÉRICO e OPT-IN: só ativa se ``BOTAPP_SSO_SECRET`` estiver definido.
Um provedor de identidade externo (qualquer um) emite um token curto assinado
com o segredo compartilhado; esta view valida, casa/cria o usuário pelo E-MAIL e
faz login. Não há nada específico de empresa aqui — issuer/audience/segredo são
configuráveis por ambiente.

Formato do token: ``base64url(payloadJSON).base64url(HMAC-SHA256(payload, secret))``
Payload (todos os campos são opcionais exceto sub/nonce/iss/aud/iat/exp):
  sub        e-mail do usuário (chave de casamento)
  name       nome de exibição (usado ao criar o usuário)
  perfil     se == "administrador" → promove a staff+superuser (só promove)
  dep        departamento → guardado na sessão p/ o escopo (ver scoping.py)
  can_edit   bool → guardado na sessão; habilita ações de edição (ex.: toggle bot)
  iat, exp   unix seconds;  nonce  256 bits (single-use, anti-replay via cache)
  iss, aud   validados contra BOTAPP_SSO_ISSUER / BOTAPP_SSO_AUDIENCE (quando setados)
"""
import base64
import hashlib
import hmac
import json
import os
import time

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.core.cache import cache
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .scoping import SESSION_CAN_EDIT_KEY, SESSION_DEPARTMENT_KEY

User = get_user_model()

CLOCK_SKEW = 30    # tolerância de relógio (s)
NONCE_TTL = 180    # janela anti-replay (s) — deve ser > TTL do token
BACKEND = "django.contrib.auth.backends.ModelBackend"


def _cfg(nome, default=""):
    v = os.getenv(nome)
    if v is None:
        v = getattr(settings, nome, default)
    return v or default


def sso_habilitado():
    return bool(_cfg("BOTAPP_SSO_SECRET"))


def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _verificar(token, secret, issuer, audience):
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        raw = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
    except Exception:
        return None
    esperado = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(esperado, sig):
        return None
    try:
        p = json.loads(raw)
    except Exception:
        return None
    if issuer and p.get("iss") != issuer:
        return None
    if audience and p.get("aud") != audience:
        return None
    agora = int(time.time())
    if agora > int(p.get("exp", 0)) + CLOCK_SKEW:
        return None
    if int(p.get("iat", 0)) - CLOCK_SKEW > agora:
        return None
    return p


@csrf_exempt
@require_GET
def sso_login(request):
    secret = _cfg("BOTAPP_SSO_SECRET")
    token = request.GET.get("t", "")
    if not secret or not token:
        return redirect("login")

    p = _verificar(token, secret, _cfg("BOTAPP_SSO_ISSUER"), _cfg("BOTAPP_SSO_AUDIENCE", "botapp"))
    if not p:
        return redirect("login")

    nonce = p.get("nonce", "")
    if not nonce or not cache.add(f"botapp_sso_nonce:{nonce}", 1, timeout=NONCE_TTL):
        return redirect("login")  # replay / sem nonce

    email = (p.get("sub") or "").strip().lower()
    if not email:
        return redirect("login")

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        base = (email.split("@")[0] or "user")[:150]
        username = base
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{i}"[:150]
            i += 1
        user = User(username=username, email=email,
                    first_name=(p.get("name") or "")[:150], is_active=True)
        user.set_unusable_password()
        user.save()

    if not user.is_active:
        return redirect("login")

    # perfil administrador → admin do dashboard (staff+superuser). Só PROMOVE:
    # nunca rebaixa um superusuário existente que não veio como admin no token.
    perfil = (p.get("perfil") or "").strip().lower()
    if perfil == "administrador" and not (user.is_superuser and user.is_staff):
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])

    login(request, user, backend=BACKEND)
    # Contexto por sessão (não-durável): departamento p/ o escopo e permissão de
    # edição. Setado DEPOIS do login() (que rotaciona a sessão).
    request.session[SESSION_DEPARTMENT_KEY] = (p.get("dep") or "").strip()
    request.session[SESSION_CAN_EDIT_KEY] = bool(p.get("can_edit"))
    return redirect("/")
