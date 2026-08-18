"""Contexto global mínimo dos templates."""
from .ci_sync import ci_enabled as _ci_enabled


def flags(request):
    """Expõe as chaves de feature ao template.

    O item de menu do CI não pode aparecer quando a integração está desligada —
    e a decisão é do ambiente, não do template.
    """
    return {'ci_enabled': _ci_enabled()}
