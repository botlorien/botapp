"""Telas da integração de CI.

Regra que atravessa este arquivo: o token da conexão **nunca** chega ao
navegador. O log de job é PROXEADO — o servidor busca com o token e transmite o
conteúdo. Ver docs/ci-integration-design.md §5 e §8.
"""
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import scoping
from .ci_client import CIConfigError, CIError, client_for
from .ci_sync import ci_enabled, log_tail_bytes
from .models import Bot, CIConnection, CIJob, CIPipeline, CIProject

logger = logging.getLogger(__name__)

_staff = user_passes_test(lambda u: u.is_active and u.is_staff)


def _exige_ci(request):
    if not ci_enabled():
        raise Http404('integração de CI desligada (BOTAPP_CI_ENABLED)')


def _projetos_no_escopo(request, qs):
    """Aplica o mesmo escopo por departamento que o resto do painel.

    Projeto sem vínculo com bot não tem departamento para comparar, então só
    aparece para staff — melhor invisível do que visível para quem não deveria.
    """
    deps = scoping.deps_visiveis(request)
    if deps is None:
        return qs
    return qs.filter(bot__department__in=deps)


# ── conexões ───────────────────────────────────────────────────────────────
@login_required
@_staff
def connection_list(request):
    _exige_ci(request)
    conexoes = CIConnection.objects.all().order_by('name')
    # o fingerprint sai da propriedade do modelo no template: identifica o token
    # sem revelá-lo, e sem precisar de dict auxiliar aqui
    return render(request, 'botapp/ci_connections.html', {'connections': conexoes})


@login_required
@_staff
@require_POST
def connection_test(request, connection_id):
    _exige_ci(request)
    conexao = get_object_or_404(CIConnection, id=connection_id)
    try:
        info = client_for(conexao).testar_conexao()
        return JsonResponse({'ok': True, 'detalhe': info})
    except (CIError, CIConfigError) as e:
        # a mensagem já vem mascarada pelo cliente
        return JsonResponse({'ok': False, 'erro': str(e)}, status=400)


@login_required
@_staff
@require_POST
def connection_sync(request, connection_id):
    _exige_ci(request)
    from .ci_sync import sync_connection
    conexao = get_object_or_404(CIConnection, id=connection_id)
    resultado = sync_connection(conexao, forcar_descoberta=True)
    return JsonResponse({'ok': 'erro' not in resultado, 'resultado': resultado})


# ── projetos ───────────────────────────────────────────────────────────────
@login_required
def project_list(request):
    _exige_ci(request)
    qs = CIProject.objects.select_related('connection', 'bot')
    qs = _projetos_no_escopo(request, qs)

    busca = (request.GET.get('q') or '').strip()
    if busca:
        qs = qs.filter(path__icontains=busca)
    status = (request.GET.get('status') or '').strip()
    if status:
        qs = qs.filter(last_pipeline_status=status)
    if request.GET.get('monitored') == '1':
        qs = qs.filter(monitored=True)
    if request.GET.get('problemas') == '1':
        qs = qs.filter(last_pipeline_status__in=['failed', 'canceled'])

    qs = qs.order_by('-last_pipeline_at', 'path')
    paginator = Paginator(qs, 50)
    pagina = paginator.get_page(request.GET.get('page'))
    return render(request, 'botapp/ci_projects.html', {
        'projects': pagina, 'page_obj': pagina, 'total': paginator.count,
        'q': busca, 'status': status,
        'pode_editar': scoping.pode_editar(request),
    })


@login_required
def project_detail(request, project_id):
    _exige_ci(request)
    projeto = get_object_or_404(
        _projetos_no_escopo(request, CIProject.objects.select_related('bot')),
        id=project_id)
    pipelines = projeto.pipelines.order_by('-created_at')[:50]
    return render(request, 'botapp/ci_project_detail.html', {
        'project': projeto,
        'schedules': projeto.schedules.order_by('-active', 'cron'),
        'pipelines': pipelines,
        'bots': Bot.objects.order_by('name') if scoping.pode_editar(request) else [],
        'pode_editar': scoping.pode_editar(request),
    })


@login_required
@require_POST
def project_toggle(request, project_id):
    """Liga/desliga monitoramento e varredura de log de um projeto."""
    _exige_ci(request)
    if not scoping.pode_editar(request):
        return JsonResponse({'ok': False, 'erro': 'sem permissão'}, status=403)
    projeto = get_object_or_404(CIProject, id=project_id)
    campo = request.POST.get('campo')
    if campo not in ('monitored', 'scan_logs'):
        return JsonResponse({'ok': False, 'erro': 'campo inválido'}, status=400)
    setattr(projeto, campo, not getattr(projeto, campo))
    projeto.save(update_fields=[campo])
    return JsonResponse({'ok': True, 'campo': campo,
                         'valor': getattr(projeto, campo)})


@login_required
@require_POST
def project_link_bot(request, project_id):
    """Vincula (ou desvincula) o projeto a um bot instrumentado pelo SDK.

    Confirmação MANUAL de propósito: casar por heurística de nome e errar
    atribuiria telemetria ao bot errado, o que é pior do que não casar.
    """
    _exige_ci(request)
    if not scoping.pode_editar(request):
        return JsonResponse({'ok': False, 'erro': 'sem permissão'}, status=403)
    projeto = get_object_or_404(CIProject, id=project_id)
    bot_id = (request.POST.get('bot_id') or '').strip()
    projeto.bot = get_object_or_404(Bot, id=bot_id) if bot_id else None
    projeto.save(update_fields=['bot'])
    return redirect('ci_project_detail', project_id=projeto.id)


@login_required
@require_POST
def bind_from_bot(request, bot_id):
    """Vincula um projeto de CI a partir da tela do BOT.

    Existe porque o caminho natural de quem opera é entrar pelo bot, não pelo
    projeto de CI — obrigar o contrário escondia a funcionalidade.
    """
    _exige_ci(request)
    if not scoping.pode_editar(request):
        return JsonResponse({'ok': False, 'erro': 'sem permissão'}, status=403)
    bot = get_object_or_404(Bot, id=bot_id)
    if not scoping.bot_no_escopo(request, bot):
        raise Http404
    project_id = (request.POST.get('project_id') or '').strip()
    if project_id:
        projeto = get_object_or_404(CIProject, id=project_id)
        projeto.bot = bot
        projeto.save(update_fields=['bot'])
    return redirect('bot_detail', bot_id=bot.id)


# ── pipelines e log ────────────────────────────────────────────────────────
@login_required
def pipeline_detail(request, pipeline_id):
    _exige_ci(request)
    pipeline = get_object_or_404(
        CIPipeline.objects.select_related('project', 'project__bot'),
        id=pipeline_id)
    if not _projetos_no_escopo(
            request, CIProject.objects.filter(id=pipeline.project_id)).exists():
        raise Http404
    return render(request, 'botapp/ci_pipeline_detail.html', {
        'pipeline': pipeline,
        'jobs': pipeline.jobs.order_by('id'),
    })


@login_required
def job_log(request, job_id):
    """Transmite o log do job buscando-o com o token no SERVIDOR.

    Texto puro de propósito: log de CI é conteúdo não confiável, e servi-lo como
    text/plain com nosniff fecha a porta para XSS via conteúdo de log.
    """
    _exige_ci(request)
    job = get_object_or_404(
        CIJob.objects.select_related('pipeline__project__connection',
                                     'pipeline__project__bot'),
        id=job_id)
    projeto = job.pipeline.project
    if not _projetos_no_escopo(
            request, CIProject.objects.filter(id=projeto.id)).exists():
        raise Http404

    try:
        cliente = client_for(projeto.connection)
    except (CIError, CIConfigError) as e:
        return HttpResponse(f'não foi possível falar com o CI: {e}',
                            content_type='text/plain; charset=utf-8', status=502)

    def _gerar():
        try:
            for pedaco in cliente.trace_stream(projeto.external_id, job.external_id):
                yield pedaco
        except (CIError, CIConfigError) as e:
            yield f'\n[erro ao ler o log: {e}]\n'.encode()

    resposta = StreamingHttpResponse(_gerar(),
                                     content_type='text/plain; charset=utf-8')
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Content-Disposition'] = f'inline; filename="job-{job.external_id}.log"'
    return resposta


@login_required
def job_log_excerpt(request, job_id):
    """Cauda já persistida (falha/suspeita) — não vai ao CI, é leitura local."""
    _exige_ci(request)
    job = get_object_or_404(
        CIJob.objects.select_related('pipeline__project__bot'), id=job_id)
    if not _projetos_no_escopo(
            request,
            CIProject.objects.filter(id=job.pipeline.project_id)).exists():
        raise Http404
    corpo = job.log_excerpt or '(nenhuma cauda de log guardada para este job)'
    resposta = HttpResponse(corpo, content_type='text/plain; charset=utf-8')
    resposta['X-Content-Type-Options'] = 'nosniff'
    return resposta


@login_required
def ci_overview(request):
    """Visão que junta as duas fontes: o que o SDK contou × o que o CI observou.

    É aqui que aparece o caso que o SDK sozinho nunca mostra: projeto com
    execução recente no CI e nenhum registro de task — o bot rodou e não
    instrumentou.
    """
    _exige_ci(request)
    qs = _projetos_no_escopo(
        request,
        CIProject.objects.select_related('bot').filter(monitored=True))

    sem_instrumentacao = []
    for projeto in qs.exclude(last_pipeline_at=None)[:500]:
        if projeto.bot_id is None:
            continue
        ultima_task = projeto.bot.last_execution_at
        if ultima_task is None or (projeto.last_pipeline_at
                                   and projeto.last_pipeline_at > ultima_task):
            sem_instrumentacao.append(projeto)

    return render(request, 'botapp/ci_overview.html', {
        'total_monitorados': qs.count(),
        'sem_execucao': qs.filter(last_pipeline_at=None).count(),
        'com_falha': qs.filter(
            last_pipeline_status__in=['failed', 'canceled']).count(),
        'mascarados': CIPipeline.objects.filter(
            project__in=qs, has_masked_error=True).count(),
        'sem_instrumentacao': sem_instrumentacao[:50],
        'agora': timezone.now(),
    })
