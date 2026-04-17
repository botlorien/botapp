import re
import logging

from django.db import connection

logger = logging.getLogger(__name__)

_SCHEMA_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def ensure_schema_exists(schema_name):
    """Cria o schema se não existir. Valida o nome para evitar SQL injection.

    CREATE SCHEMA não aceita placeholders (%s) em PostgreSQL — o nome tem que
    ser interpolado literalmente. Por isso validamos estritamente contra o
    padrão de identificador SQL antes de montar a query.
    """
    if not schema_name or not _SCHEMA_NAME_RE.match(schema_name):
        raise ValueError(
            f"Nome de schema inválido: {schema_name!r}. "
            "Use apenas letras, números e underscore (até 63 caracteres, "
            "começando com letra ou _)."
        )
    logger.info("Garantindo existência do schema %s", schema_name)
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
