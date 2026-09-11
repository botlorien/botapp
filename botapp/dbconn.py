"""Conexão de banco em processo que vive muito tempo.

POR QUE ESTE MÓDULO EXISTE. O Django foi desenhado para servidor web: ele fecha
conexões obsoletas no início e no fim de **cada request**. Um processo que não
atende requests — um laço de agendamento, um worker, um bot que roda em ciclos —
nunca passa por esse ponto, então mantém a mesma conexão aberta indefinidamente.

Quando o servidor de banco reinicia (ou um proxy/firewall derruba a sessão
ociosa), o driver não é avisado: o socket está fechado do outro lado e só se
descobre isso ao tentar usá-lo. A partir daí **toda** operação falha com
`InterfaceError: connection already closed`, e capturar a exceção não adianta —
a próxima tentativa usa a mesma conexão morta.

Caso real (10/09/2026) com os três consumidores deste pacote:

* o laço de sincronização de CI capturava a exceção, logava e seguia para o
  ciclo seguinte com a conexão morta. Ficou **14 horas** sem sincronizar, com o
  processo vivo e o último status gravado como `ok`: o painel cego, sem nada
  indicando isso;
* o laço de alertas tem o mesmo desenho e o mesmo risco;
* o SDK (`@app.task`) falhava no registro da task, antes mesmo de criar o
  TaskLog. Num bot de execução única é uma execução perdida; num bot em laço,
  são todas as seguintes.

A saída não é capturar melhor, é **renovar**: `close_old_connections()` fecha o
que estiver obsoleto ou inutilizável (o `is_usable()` do Django detecta o socket
morto), e a operação seguinte abre uma conexão nova. O custo é um `SELECT 1` por
ciclo.
"""
import logging

from django.db import connections
from django.db.utils import InterfaceError, OperationalError

logger = logging.getLogger(__name__)

#: Erros que indicam conexão perdida — e só eles justificam tentar de novo.
#: `OperationalError` cobre "server closed the connection unexpectedly";
#: `InterfaceError`, o "connection already closed" de quem já tinha o socket.
ERROS_DE_CONEXAO = (InterfaceError, OperationalError)


def renovar_conexoes() -> None:
    """Descarta conexões inutilizáveis/obsoletas. Nunca levanta.

    Chame antes de tocar no banco em processo longevo: o custo é desprezível
    quando a conexão está boa e evita o ciclo perdido quando não está.

    **Conexão com transação aberta é pulada.** É por isso que aqui não se usa o
    `close_old_connections()` direto: ele delega a `close_if_unusable_or_obsolete`,
    que fecha a conexão quando o autocommit está desligado — exatamente o estado
    de quem está dentro de um `atomic()`. Fechar ali descartaria o trabalho da
    transação em curso do chamador. (O sintoma aparece primeiro em teste, porque
    `TestCase` embrulha cada teste numa transação; o risco em produção é o
    mesmo.)

    Renovar é preventivo — se ele próprio falhar, o trabalho útil ainda merece
    a tentativa, então o erro é registrado e engolido de propósito.
    """
    try:
        for conexao in connections.all():
            if conexao.in_atomic_block:
                logger.debug(
                    'conexão %s está em transação; não renovo agora',
                    conexao.alias)
                continue
            conexao.close_if_unusable_or_obsolete()
    except Exception as erro:            # noqa: BLE001 - preventivo, best-effort
        logger.debug('não consegui renovar as conexões do banco (%s)', erro)


def executar_reconectando(funcao, *args, tentativas: int = 2, **kwargs):
    """Executa `funcao`; se falhar por conexão perdida, renova e tenta de novo.

    Para o caso em que a conexão morre **durante** o trabalho — típico de tarefa
    longa, onde o começo grava normalmente e a gravação do fim já encontra o
    socket morto. Sem isso, a execução fica registrada como iniciada para
    sempre, que é o padrão que gera alerta de execução órfã.

    Só erro de conexão é repetido: repetir erro de programação esconderia o
    defeito e, numa escrita, poderia dobrar o efeito. Esgotadas as tentativas, o
    erro sobe — banco fora do ar de verdade não pode virar silêncio.

    Use apenas com operações idempotentes (`save` de um registro existente,
    `get_or_create`): uma segunda tentativa de `create` puro pode duplicar se a
    primeira tiver chegado ao servidor antes de a conexão cair.
    """
    ultimo = max(1, int(tentativas))
    for tentativa in range(1, ultimo + 1):
        try:
            return funcao(*args, **kwargs)
        except ERROS_DE_CONEXAO as erro:
            if tentativa >= ultimo:
                raise
            logger.warning(
                'conexão com o banco perdida (%s); renovando e tentando de novo '
                '(%d/%d)', type(erro).__name__, tentativa + 1, ultimo)
            renovar_conexoes()
