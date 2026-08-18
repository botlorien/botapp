"""Sincronização com o servidor de CI e derivação de alertas.

Duas responsabilidades separadas de propósito:
  - `sync_projects`  : descoberta (projetos + agendamentos), intervalo largo
  - `sync_pipelines` : execuções dos projetos monitorados, intervalo curto

Ver docs/ci-integration-design.md.
"""
import logging
import os
import re
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .ci_client import CIConfigError, CIError, client_for
from .models import (Alert, CIConnection, CIJob, CIPipeline, CIProject,
                     CISchedule)

logger = logging.getLogger(__name__)

# Padrões GENÉRICOS. A lista de cada instalação vem de env — a default não pode
# ser a de nenhum cliente específico.
ERROR_PATTERNS_DEFAULT = [
    'Traceback (most recent call last)',
    'CRITICAL',
    'FATAL',
]


def _lista_env(nome, default=None):
    bruto = os.getenv(nome, '')
    itens = [p.strip() for p in bruto.split('|') if p.strip()]
    return itens or list(default or [])


def error_patterns():
    return _lista_env('BOTAPP_CI_ERROR_PATTERNS', ERROR_PATTERNS_DEFAULT)


def ignore_patterns():
    return _lista_env('BOTAPP_CI_IGNORE_PATTERNS', [])


def _flag(nome, default):
    return os.getenv(nome, str(default)).strip().lower() == 'true'


def store_triggered_by():
    """Dado pessoal (quem disparou). Ligado por default; desligável por env."""
    return _flag('BOTAPP_CI_STORE_TRIGGERED_BY', True)


def alert_max_age_days():
    """Idade máxima de um pipeline para ele ainda gerar alerta.

    Existe porque a carga inicial importa histórico: sem este corte, um projeto
    dormente cuja última execução falhou há meses vira alerta novo hoje — ruído
    que não é acionável e que empurra o alerta real para fora da tela.
    """
    try:
        return max(0, int(os.getenv('BOTAPP_CI_ALERT_MAX_AGE_DAYS', '7')))
    except ValueError:
        return 7


def log_tail_bytes():
    try:
        return max(1024, int(os.getenv('BOTAPP_CI_LOG_TAIL_BYTES', '65536')))
    except ValueError:
        return 65536


_ANSI = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

# Padrões que NÃO devem ser persistidos no banco do painel. O servidor de CI
# mascara as variáveis marcadas como protegidas, mas nada impede um script de
# imprimir um valor por conta própria — e a cauda do log fica gravada aqui.
# Redigir na entrada é mais barato que descobrir depois que o dump de backup
# do painel virou um repositório de credenciais.
_SEGREDOS = [
    (re.compile(r'\bgl(?:pat|rt)-[A-Za-z0-9_-]{15,}'), 'gl***-[REDIGIDO]'),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), 'AKIA[REDIGIDO]'),
    (re.compile(r'\bghp_[A-Za-z0-9]{20,}'), 'ghp_[REDIGIDO]'),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}'), 'xox*-[REDIGIDO]'),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._-]{20,}'), 'Bearer [REDIGIDO]'),
    (re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----'
                r'[\s\S]*?-----END (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----'),
     '[CHAVE PRIVADA REDIGIDA]'),
    # senha embutida em URL: preserva o host, some com a credencial
    (re.compile(r'://([^/\s:@]+):([^@/\s]{4,})@'), r'://\1:[REDIGIDO]@'),
    # valor literal após password=/senha=/secret= (a REFERÊNCIA $VAR fica)
    (re.compile(r'(?i)\b(password|passwd|senha|secret|token|api[_-]?key)'
                r'(\s*[=:]\s*)(?!\$)([\'"]?)([^\s\'"&]{6,})'),
     r'\1\2\3[REDIGIDO]'),
]


def redigir_segredos(texto):
    """Mascara o que parece credencial antes de gravar o log no banco."""
    for padrao, troca in _SEGREDOS:
        texto = padrao.sub(troca, texto)
    return texto


def limpar_ansi(texto):
    """Remove códigos de cor do trace.

    Vale por dois motivos: o log fica legível na tela, e o casamento de padrão
    deixa de depender de onde o servidor de CI inseriu um código de cor no meio
    da linha — um `\x1b[31;1m` antes de "Traceback" já bastaria para o padrão
    passar batido.
    """
    return _ANSI.sub('', texto or '')


def _dt(valor):
    return parse_datetime(valor) if valor else None


def _duracao(segundos):
    return timedelta(seconds=segundos) if segundos else None


# ═══════════════════════════════════════════════════════════════════════════
# Descoberta: projetos e agendamentos
# ═══════════════════════════════════════════════════════════════════════════

def sync_projects(connection, cliente=None):
    """Descobre projetos do namespace e os agendamentos de cada um.

    Devolve dict com contadores. Falha de UM projeto não aborta o ciclo.
    """
    cliente = cliente or client_for(connection)
    criados = atualizados = agendamentos = 0
    vistos = []

    for bruto in cliente.projetos(connection.namespace):
        projeto, novo = CIProject.objects.update_or_create(
            connection=connection, external_id=bruto['id'],
            defaults={
                'path': bruto.get('path_with_namespace') or bruto.get('path', ''),
                'name': bruto.get('name', ''),
                'web_url': bruto.get('web_url', '') or '',
                'default_branch': bruto.get('default_branch') or '',
                'archived': bool(bruto.get('archived')),
            })
        vistos.append(projeto.id)
        criados += int(novo)
        atualizados += int(not novo)
        try:
            agendamentos += _sync_schedules(cliente, projeto)
        except (CIError, CIConfigError) as e:
            # projeto sem permissão de leitura de agendamento não pode derrubar
            # a descoberta inteira
            projeto.last_sync_error = f'agendamentos: {e}'
            projeto.save(update_fields=['last_sync_error'])
            logger.warning('agendamentos de %s falharam: %s', projeto.path, e)

    connection.last_discovery_at = timezone.now()
    connection.last_sync_at = timezone.now()
    connection.last_sync_status = CIConnection.SyncStatus.OK
    connection.save(update_fields=['last_discovery_at', 'last_sync_at',
                                   'last_sync_status'])
    return {'projetos_criados': criados, 'projetos_atualizados': atualizados,
            'agendamentos': agendamentos, 'vistos': len(vistos)}


def _sync_schedules(cliente, projeto):
    n = 0
    externos = []
    for s in cliente.agendamentos(projeto.external_id):
        CISchedule.objects.update_or_create(
            project=projeto, external_id=s['id'],
            defaults={
                'description': (s.get('description') or '')[:255],
                'cron': s.get('cron') or '',
                'cron_timezone': s.get('cron_timezone') or '',
                'active': bool(s.get('active')),
                'next_run_at': _dt(s.get('next_run_at')),
            })
        externos.append(s['id'])
        n += 1
    # agendamento removido no servidor deixa de existir aqui
    projeto.schedules.exclude(external_id__in=externos).delete()
    return n


# ═══════════════════════════════════════════════════════════════════════════
# Execuções: pipelines e jobs
# ═══════════════════════════════════════════════════════════════════════════

def sync_pipelines(connection, cliente=None, limite_por_projeto=50,
                   limite_primeira_vez=10):
    """Sincroniza execuções dos projetos monitorados.

    `limite_primeira_vez` é menor de propósito: num projeto ainda sem cursor,
    puxar 50 pipelines (com jobs e, se ligado, logs) multiplicado por centenas
    de projetos faz o PRIMEIRO ciclo levar horas — e o valor está no que é NOVO,
    não em importar a história. Depois do primeiro ciclo o cursor entra em ação
    e o limite maior praticamente nunca é atingido.
    """
    cliente = cliente or client_for(connection)
    total_novos = total_alertas = 0
    # inativo = arquivado no CI OU arquivado aqui. Nos dois casos não vale
    # gastar chamada de API nem gerar alerta: ninguém vai agir sobre ele.
    projetos = connection.projects.filter(monitored=True, archived=False,
                                          local_archived=False)

    for projeto in projetos:
        limite = limite_por_projeto if projeto.pipelines_cursor else limite_primeira_vez
        try:
            novos, alertas = _sync_pipelines_projeto(cliente, projeto, limite)
            total_novos += novos
            total_alertas += alertas
            if projeto.last_sync_error:
                projeto.last_sync_error = ''
                projeto.save(update_fields=['last_sync_error'])
            # marca progresso a cada projeto: um ciclo longo não pode deixar o
            # painel exibindo "nunca sincronizado" enquanto o sync trabalha
            connection.last_sync_at = timezone.now()
            connection.last_sync_status = CIConnection.SyncStatus.OK
            connection.save(update_fields=['last_sync_at', 'last_sync_status'])
        except (CIError, CIConfigError) as e:
            # isolamento por projeto: 403/arquivado/timeout de um não interrompe
            # a varredura dos outros
            projeto.last_sync_error = str(e)[:500]
            projeto.save(update_fields=['last_sync_error'])
            logger.warning('sync de %s falhou: %s', projeto.path, e)

    return {'pipelines_novos': total_novos, 'alertas': total_alertas,
            'projetos': projetos.count()}


def _sync_pipelines_projeto(cliente, projeto, limite):
    cursor = projeto.pipelines_cursor
    novos = alertas = 0
    mais_recente = cursor
    guardar_autor = store_triggered_by()

    for bruto in cliente.pipelines(
            projeto.external_id,
            updated_after=cursor.isoformat() if cursor else None,
            limite=limite):
        if bruto.get('status') in ('running', 'pending', 'created', 'waiting_for_resource'):
            continue  # ainda em andamento: entra no próximo ciclo

        detalhe = cliente.pipeline(projeto.external_id, bruto['id'])
        criado = _dt(detalhe.get('created_at'))
        agendamento = None
        if detalhe.get('source') == 'schedule':
            agendamento = projeto.schedules.order_by('-active', 'external_id').first()

        autor = ''
        if guardar_autor:
            autor = ((detalhe.get('user') or {}).get('username') or '')[:150]

        pipeline, novo = CIPipeline.objects.update_or_create(
            project=projeto, external_id=detalhe['id'],
            defaults={
                'iid': detalhe.get('iid'),
                'status': detalhe.get('status', ''),
                'source': detalhe.get('source', '') or '',
                'ref': detalhe.get('ref', '') or '',
                'sha': (detalhe.get('sha') or '')[:64],
                'commit_title': (detalhe.get('name') or '')[:255],
                'web_url': detalhe.get('web_url', '') or '',
                'schedule': agendamento,
                'triggered_by': autor,
                'created_at': criado,
                'started_at': _dt(detalhe.get('started_at')),
                'finished_at': _dt(detalhe.get('finished_at')),
                'duration': _duracao(detalhe.get('duration')),
            })
        novos += int(novo)

        if criado and (mais_recente is None or criado > mais_recente):
            mais_recente = criado

        try:
            _sync_jobs(cliente, pipeline)
            if novo:
                alertas += _avaliar_pipeline(cliente, pipeline)
        except (CIError, CIConfigError) as e:
            # isolamento por PIPELINE: sem isto, falhar ao listar jobs de um
            # pipeline descartaria o cursor e a contagem dos anteriores, e o
            # ciclo seguinte releria tudo de novo
            logger.warning('jobs/avaliação do pipeline %s de %s falharam: %s',
                           pipeline.external_id, projeto.path, e)

    if mais_recente and mais_recente != cursor:
        projeto.pipelines_cursor = mais_recente
        ultimo = projeto.pipelines.order_by('-created_at').first()
        if ultimo:
            projeto.last_pipeline_at = ultimo.created_at
            projeto.last_pipeline_status = ultimo.status
            projeto.last_pipeline_external_id = ultimo.external_id
        projeto.save(update_fields=['pipelines_cursor', 'last_pipeline_at',
                                    'last_pipeline_status',
                                    'last_pipeline_external_id'])
    return novos, alertas


def _sync_jobs(cliente, pipeline):
    for j in cliente.jobs(pipeline.project.external_id, pipeline.external_id):
        CIJob.objects.update_or_create(
            pipeline=pipeline, external_id=j['id'],
            defaults={
                'name': (j.get('name') or '')[:255],
                'stage': (j.get('stage') or '')[:100],
                'status': j.get('status', ''),
                'runner_description': ((j.get('runner') or {}).get('description')
                                       or '')[:255],
                'failure_reason': (j.get('failure_reason') or '')[:100],
                'web_url': j.get('web_url', '') or '',
                'started_at': _dt(j.get('started_at')),
                'finished_at': _dt(j.get('finished_at')),
                'duration': _duracao(j.get('duration')),
            })


# ═══════════════════════════════════════════════════════════════════════════
# Alertas
# ═══════════════════════════════════════════════════════════════════════════

def _abrir_alerta(tipo, projeto, mensagem, severidade, payload):
    """Cria alerta se não houver um igual em aberto (evita repetir a cada ciclo)."""
    if projeto.archived or projeto.local_archived:
        return 0   # projeto inativo não gera alerta
    dedupe = Alert.objects.filter(type=tipo, resolved_at__isnull=True,
                                  bot=projeto.bot)
    if projeto.bot_id is None:
        dedupe = dedupe.filter(payload__project_id=projeto.id)
    if dedupe.exists():
        return 0
    Alert.objects.create(type=tipo, severity=severidade, bot=projeto.bot,
                         message=mensagem, payload=payload)
    return 1


def _avaliar_pipeline(cliente, pipeline):
    projeto = pipeline.project
    limite_dias = alert_max_age_days()
    if limite_dias and pipeline.created_at:
        idade = timezone.now() - pipeline.created_at
        if idade > timedelta(days=limite_dias):
            # execução antiga demais para ser acionável (tipicamente vinda da
            # carga inicial de histórico)
            return 0
    base = {'project_id': projeto.id, 'project_path': projeto.path,
            'pipeline_id': pipeline.external_id,
            # ids internos: sem eles o alerta não consegue linkar para a tela
            # do pipeline nem para o log, e o operador só pode reconhecer/
            # resolver sem ver o que aconteceu
            'pipeline_db_id': pipeline.id,
            'web_url': pipeline.web_url,
            'ref': pipeline.ref, 'source': pipeline.source}

    if pipeline.status == 'failed':
        jobs = list(pipeline.jobs.filter(status='failed'))
        for job in jobs:
            _capturar_cauda(cliente, job)
        return _abrir_alerta(
            Alert.Type.PIPELINE_FAILED, projeto,
            f'Pipeline #{pipeline.external_id} de {projeto.path} falhou '
            f'({", ".join(j.name for j in jobs) or "sem job identificado"})',
            Alert.Severity.HIGH,
            {**base, 'jobs_falhos': [j.name for j in jobs],
             'job_db_id': jobs[0].id if jobs else None})

    if pipeline.status == 'success' and projeto.scan_logs:
        achado = _varrer_log_verde(cliente, pipeline)
        if achado:
            job, padrao = achado
            return _abrir_alerta(
                Alert.Type.PIPELINE_MASKED_ERROR, projeto,
                f'Pipeline #{pipeline.external_id} de {projeto.path} terminou '
                f'VERDE mas o log do job "{job.name}" contém {padrao!r} — '
                f'a exceção foi engolida e o processo saiu com código 0',
                Alert.Severity.HIGH,
                {**base, 'job': job.name, 'pattern': padrao,
                 'job_db_id': job.id})
    return 0


def _varrer_log_verde(cliente, pipeline):
    """Procura padrão de erro no log de pipeline BEM-SUCEDIDO.

    É o caso mais difícil de achar por outros meios: o CI diz OK e o trabalho não
    aconteceu. Custa uma chamada de log por job, e é por isso que `scan_logs` é
    opt-in por projeto.
    """
    padroes = error_patterns()
    ignorar = ignore_patterns()
    for job in pipeline.jobs.all():
        try:
            texto, _ = cliente.trace(pipeline.project.external_id,
                                     job.external_id, max_bytes=log_tail_bytes())
        except (CIError, CIConfigError) as e:
            logger.info('log do job %s indisponível: %s', job.external_id, e)
            continue
        linhas = [l for l in limpar_ansi(texto).splitlines()
                  if not any(ig in l for ig in ignorar)]
        limpo = '\n'.join(linhas)
        for padrao in padroes:
            if padrao in limpo:
                job.log_excerpt = redigir_segredos(limpo[-log_tail_bytes():])
                job.log_excerpt_at = timezone.now()
                job.matched_pattern = padrao[:255]
                job.save(update_fields=['log_excerpt', 'log_excerpt_at',
                                        'matched_pattern'])
                pipeline.has_masked_error = True
                pipeline.log_scanned_at = timezone.now()
                pipeline.save(update_fields=['has_masked_error', 'log_scanned_at'])
                return job, padrao
    pipeline.log_scanned_at = timezone.now()
    pipeline.save(update_fields=['log_scanned_at'])
    return None


def _capturar_cauda(cliente, job):
    """Guarda só a cauda do log de um job que falhou — o fim tem o motivo."""
    try:
        texto, truncado = cliente.trace(job.pipeline.project.external_id,
                                        job.external_id,
                                        max_bytes=log_tail_bytes())
    except (CIError, CIConfigError):
        return
    aviso = '[...log truncado; exibindo o final...]\n' if truncado else ''
    job.log_excerpt = aviso + redigir_segredos(limpar_ansi(texto))
    job.log_excerpt_at = timezone.now()
    job.save(update_fields=['log_excerpt', 'log_excerpt_at'])


def fechar_alertas_de_inativos(connection):
    """Fecha alertas de projeto que virou inativo (arquivado no CI ou aqui).

    Sem isto, arquivar um repositório não limpa o painel: o alerta continua
    aberto para sempre, sobre algo que ninguém vai mais consertar.
    """
    from django.utils import timezone as tz
    inativos = connection.projects.filter(
        models.Q(archived=True) | models.Q(local_archived=True)
    ).values_list('id', flat=True)
    if not inativos:
        return 0
    abertos = Alert.objects.filter(
        type__in=[Alert.Type.PIPELINE_FAILED, Alert.Type.PIPELINE_MASKED_ERROR,
                  Alert.Type.SCHEDULE_WITHOUT_RUN, Alert.Type.PROJECT_NEVER_RAN],
        resolved_at__isnull=True)
    n = 0
    for alerta in abertos:
        if (alerta.payload or {}).get('project_id') in set(inativos):
            alerta.resolved_at = tz.now()
            alerta.payload = {**(alerta.payload or {}),
                              'fechado_por': 'projeto_inativo'}
            alerta.save(update_fields=['resolved_at', 'payload'])
            n += 1
    return n


def resolver_alertas_obsoletos(connection):
    """Fecha alerta de falha cujo projeto já voltou a passar depois.

    Sem isto o painel acumula alerta de pipeline que falhou às 3h e passou às
    4h — o operador perde tempo investigando algo que o próximo run já
    resolveu, e o volume de alerta velho faz o alerta novo se perder no meio.

    O critério é conservador: só resolve se existe um pipeline do MESMO projeto,
    com sucesso, criado DEPOIS do que gerou o alerta. Alerta de projeto que
    segue falhando permanece aberto.
    """
    from django.utils import timezone as tz
    resolvidos = 0
    abertos = Alert.objects.filter(
        type__in=[Alert.Type.PIPELINE_FAILED, Alert.Type.PIPELINE_MASKED_ERROR],
        resolved_at__isnull=True)

    for alerta in abertos:
        payload = alerta.payload or {}
        projeto_id = payload.get('project_id')
        pipeline_id = payload.get('pipeline_id')
        if not projeto_id or not pipeline_id:
            continue
        origem = CIPipeline.objects.filter(project_id=projeto_id,
                                           external_id=pipeline_id).first()
        if origem and origem.created_at:
            referencia = origem.created_at
        else:
            # o pipeline que gerou o alerta pode não estar no banco (carga
            # inicial limitada). Sem um fallback, esse alerta ficaria aberto
            # para sempre mesmo com o projeto já recuperado. Usa a data do
            # próprio alerta como referência — é conservador: exige sucesso
            # posterior ao momento em que o problema foi notado.
            referencia = alerta.created_at
        posterior_ok = CIPipeline.objects.filter(
            project_id=projeto_id, status='success',
            created_at__gt=referencia,
            has_masked_error=False).order_by('-created_at').first()
        if not posterior_ok:
            continue
        alerta.resolved_at = tz.now()
        alerta.save(update_fields=['resolved_at'])
        resolvidos += 1
        logger.info('alerta %s resolvido: pipeline %s do mesmo projeto passou depois',
                    alerta.id, posterior_ok.external_id)
    return resolvidos


def avaliar_agendamentos(connection, fator=3):
    """Agendamento ativo cujo último pipeline é antigo demais.

    Pega a armadilha real de agendamento que existe, está ativo e simplesmente
    não dispara — o painel de CI mostra tudo "normal" porque não há execução
    falhando; não há execução nenhuma.
    """
    alertas = 0
    agora = timezone.now()
    for projeto in connection.projects.filter(monitored=True, archived=False,
                                              local_archived=False):
        for ag in projeto.schedules.filter(active=True):
            ultimo = projeto.pipelines.filter(source='schedule').order_by(
                '-created_at').first()
            intervalo = _intervalo_estimado(ag.cron)
            if intervalo is None:
                continue
            limite = intervalo * fator
            if ultimo is None:
                alertas += _abrir_alerta(
                    Alert.Type.PROJECT_NEVER_RAN, projeto,
                    f'{projeto.path} tem agendamento ativo ({ag.cron}) e nenhuma '
                    f'execução agendada registrada',
                    Alert.Severity.MEDIUM,
                    {'project_id': projeto.id, 'project_path': projeto.path,
                     'cron': ag.cron})
            elif ultimo.created_at and (agora - ultimo.created_at) > limite:
                horas = int((agora - ultimo.created_at).total_seconds() // 3600)
                alertas += _abrir_alerta(
                    Alert.Type.SCHEDULE_WITHOUT_RUN, projeto,
                    f'{projeto.path}: agendamento ativo ({ag.cron}) sem execução '
                    f'há {horas}h — o agendamento existe e não está disparando',
                    Alert.Severity.MEDIUM,
                    {'project_id': projeto.id, 'project_path': projeto.path,
                     'cron': ag.cron, 'horas_sem_run': horas})
    return alertas


def _intervalo_estimado(cron):
    """Intervalo aproximado de um cron de 5 campos. Só o suficiente para dizer
    "faz tempo demais" — não é um parser de cron completo, e não precisa ser."""
    partes = (cron or '').split()
    if len(partes) != 5:
        return None
    minuto, hora, dia, mes, semana = partes
    if minuto.startswith('*/'):
        try:
            return timedelta(minutes=int(minuto[2:]))
        except ValueError:
            return None
    if hora.startswith('*/'):
        try:
            return timedelta(hours=int(hora[2:]))
        except ValueError:
            return None
    if hora == '*':
        return timedelta(hours=1)
    if ',' in hora:
        return timedelta(hours=max(1, 24 // (hora.count(',') + 1)))
    if dia == '*' and mes == '*' and semana == '*':
        return timedelta(days=1)
    return timedelta(days=7)


# ═══════════════════════════════════════════════════════════════════════════
# Orquestração
# ═══════════════════════════════════════════════════════════════════════════

def sync_connection(connection, forcar_descoberta=False):
    """Um ciclo completo de uma conexão, respeitando os intervalos."""
    resultado = {'connection': connection.name}
    try:
        cliente = client_for(connection)
        agora = timezone.now()
        precisa_descobrir = (
            forcar_descoberta
            or connection.last_discovery_at is None
            or (agora - connection.last_discovery_at)
            > timedelta(minutes=connection.discovery_interval_minutes))

        if precisa_descobrir:
            resultado['descoberta'] = sync_projects(connection, cliente)

        resultado['execucoes'] = sync_pipelines(connection, cliente)
        # resolve antes de avaliar: alerta obsoleto poluindo o painel esconde o
        # alerta que importa
        resultado['alertas_resolvidos'] = resolver_alertas_obsoletos(connection)
        resultado['alertas_de_inativos'] = fechar_alertas_de_inativos(connection)
        resultado['alertas_agendamento'] = avaliar_agendamentos(connection)

        connection.last_sync_at = timezone.now()
        connection.last_sync_status = CIConnection.SyncStatus.OK
        connection.last_sync_error = ''
    except (CIError, CIConfigError) as e:
        connection.last_sync_status = CIConnection.SyncStatus.ERROR
        connection.last_sync_error = str(e)[:1000]
        resultado['erro'] = str(e)
        logger.error('sync da conexão %s falhou: %s', connection.name, e)
    connection.save(update_fields=['last_sync_at', 'last_sync_status',
                                   'last_sync_error'])
    return resultado


def ci_enabled():
    return _flag('BOTAPP_CI_ENABLED', False)
