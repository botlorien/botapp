"""Escopo de visualização por departamento (opcional, genérico).

Recurso OPT-IN: desligado por padrão (``BOTAPP_DEPARTMENT_SCOPING`` != "true"),
então instalações públicas do pacote não mudam de comportamento. Quando ligado,
um usuário NÃO-superusuário só enxerga bots (e execuções/alertas) do seu próprio
departamento. O departamento do usuário vem da sessão (setado no login, ex.: por
um SSO externo em ``request.session['botapp_department']``); o departamento do bot
é o campo ``Bot.department``. O casamento é CANÔNICO (sem acento, maiúsculo,
espaços colapsados), tolerando divergências de acento/caixa entre as duas fontes.

Nada aqui é específico de uma empresa — o departamento é um rótulo livre.
"""
import os
import unicodedata

from django.core.cache import cache

from .models import Bot

SESSION_DEPARTMENT_KEY = "botapp_department"
SESSION_CAN_EDIT_KEY = "botapp_can_edit"
SESSION_THEME_KEY = "botapp_theme"


def canon(nome):
    """Forma canônica: sem acento, maiúsculo, espaços colapsados."""
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def scoping_habilitado():
    return os.getenv("BOTAPP_DEPARTMENT_SCOPING", "false").lower() == "true"


def _departamentos_do_banco():
    """Strings distintas de Bot.department (cacheadas — mudam raramente)."""
    key = "botapp:departments:raw"
    deps = cache.get(key)
    if deps is None:
        deps = list(
            Bot.objects.exclude(department__isnull=True)
            .exclude(department__exact="")
            .values_list("department", flat=True)
            .distinct()
        )
        cache.set(key, deps, timeout=300)
    return deps


def departamentos_correspondentes(dep):
    """Valores crus de Bot.department cujo canônico == canon(dep). [] se dep vazio."""
    alvo = canon(dep)
    if not alvo:
        return []
    return [d for d in _departamentos_do_banco() if canon(d) == alvo]


def departamento_do_usuario(request):
    sess = getattr(request, "session", None)
    if sess is None:
        return ""
    return (sess.get(SESSION_DEPARTMENT_KEY) or "").strip()


def pode_editar(request):
    """Pode desativar/editar bot: superusuário OU flag can_edit da sessão (SSO)."""
    u = getattr(request, "user", None)
    if u is not None and getattr(u, "is_superuser", False):
        return True
    sess = getattr(request, "session", None)
    return bool(sess and sess.get(SESSION_CAN_EDIT_KEY))


def deps_visiveis(request):
    """Departamentos (crus) visíveis a um request de SESSÃO (dashboard HTML).

    Retorna None quando NÃO há escopo (scoping off ou superusuário → vê tudo).
    Retorna a lista de departamentos correspondentes caso contrário; lista vazia
    quando o usuário não tem departamento resolvido (bloqueio seguro).
    """
    if not scoping_habilitado():
        return None
    u = getattr(request, "user", None)
    if u is not None and getattr(u, "is_superuser", False):
        return None
    return departamentos_correspondentes(departamento_do_usuario(request))


def bot_no_escopo(request, bot):
    """True se o bot é visível ao request (para gate por URL em detail/toggle)."""
    deps = deps_visiveis(request)
    if deps is None:
        return True
    return (bot.department or "") in deps


def chave_cache_escopo(request):
    """Sufixo estável por escopo p/ chaves de cache (evita vazar dados entre deptos)."""
    deps = deps_visiveis(request)
    if deps is None:
        return "all"
    return "d:" + "|".join(sorted(canon(d) for d in deps))


def autenticado_por_sessao(request):
    """True se o request foi autenticado por SESSÃO (navegador), não por SDK
    (Token/Basic headless). Usado p/ separar humanos de clientes de máquina."""
    try:
        from rest_framework.authentication import SessionAuthentication
    except Exception:
        return False
    return isinstance(getattr(request, "successful_authenticator", None), SessionAuthentication)


def escopo_api(request):
    """Escopo para as ViewSets DRF. Só se aplica a requests autenticados por
    SESSÃO (navegador) — clientes SDK (Token/Basic) precisam ver tudo p/ registrar
    execuções. Retorna None (sem filtro) ou lista de departamentos crus."""
    if not scoping_habilitado():
        return None
    u = getattr(request, "user", None)
    if u is None or not u.is_authenticated or getattr(u, "is_superuser", False):
        return None
    if not autenticado_por_sessao(request):
        return None  # SDK (Token/Basic) → sem escopo
    return departamentos_correspondentes(departamento_do_usuario(request))
