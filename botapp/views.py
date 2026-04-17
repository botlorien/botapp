import csv
import logging
import os
from django.http import StreamingHttpResponse
from django.shortcuts import render, get_object_or_404
from .models import Bot, Task, TaskLog, Alert
from datetime import datetime
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Count, Sum, Q, F, Avg
from django.db.models.functions import ExtractHour, ExtractWeekDay
from django.db import connection
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


def _parse_date(value):
    """Retorna datetime parseado ou None. Sem fallback agressivo — o caller
    decide se ausência de data significa 'tudo'."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def _distinct_departments():
    """Lista de departamentos distintos, cacheada (raramente muda)."""
    key = 'botapp:departments:distinct'
    deps = cache.get(key)
    if deps is None:
        deps = list(
            Bot.objects.exclude(department__isnull=True)
            .exclude(department__exact='')
            .values_list('department', flat=True)
            .distinct()
            .order_by('department')
        )
        cache.set(key, deps, timeout=300)  # 5 min
    return deps


@login_required
def filter_bots(request):
    """Queryset de Bot com filtros. Usa Bot.last_status/last_execution_at
    (denormalizados pelo signal post_save de TaskLog) — sem Subquery, sem
    JOIN para obter último status.

    Filtro de período: quando fornecido, restringe aos bots cuja
    last_execution_at está na janela. Para consulta histórica completa
    (bots que executaram em qualquer momento de um período antigo), usar
    a view de logs/dashboard que vai direto em TaskLog.
    """
    name = request.GET.get("name")
    department = request.GET.get("department")
    is_active = request.GET.get('is_active')
    last_status = request.GET.get('last_status')
    os_platform = request.GET.get("os_platform")
    filter_mode = request.GET.get("filter_mode", "in")

    start_date = _parse_date(request.GET.get('start_date'))
    end_date = _parse_date(request.GET.get('end_date'))

    filters = Q()
    if name:
        filters &= Q(name__icontains=name)
    if department:
        filters &= Q(department__iexact=department)
    if is_active in ("true", "false"):
        filters &= Q(is_active=(is_active == "true"))
    if last_status:
        filters &= Q(last_status=last_status)
    if start_date:
        filters &= Q(last_execution_at__date__gte=start_date.date())
    if end_date:
        filters &= Q(last_execution_at__date__lte=end_date.date())

    bots = Bot.objects.all()

    if filters:
        bots = bots.exclude(filters) if filter_mode == "not_in" else bots.filter(filters)

    # Plataforma exige JOIN em TaskLog — mantido como filtro opcional.
    if os_platform:
        bot_ids = TaskLog.objects.filter(
            os_platform__icontains=os_platform
        ).values_list('task__bot_id', flat=True).distinct()
        if filter_mode == "not_in":
            bots = bots.exclude(id__in=bot_ids)
        else:
            bots = bots.filter(id__in=bot_ids)

    # Alias para retrocompat com o template existente que usa `latest_status`
    bots = bots.annotate(latest_status=F('last_status')).order_by('-last_execution_at', '-updated_at')
    return bots


@login_required
def bot_list(request):
    bots_qs = filter_bots(request)

    # Paginação — usa o count do paginator (1 query só).
    paginator = Paginator(bots_qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    today = datetime.now().date()
    return render(request, "botapp/bot_list.html", {
        "bots": page_obj,
        "page_obj": page_obj,
        "total_bots": paginator.count,
        "departments": _distinct_departments(),
        "today_iso": today.isoformat(),
        "seven_days_ago_iso": (today - timedelta(days=7)).isoformat(),
        "thirty_days_ago_iso": (today - timedelta(days=30)).isoformat(),
        "ninety_days_ago_iso": (today - timedelta(days=90)).isoformat(),
    })

@login_required
def bot_detail(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id)
    logs = TaskLog.objects.filter(task__bot=bot).select_related('task', 'task__bot')

    start = _parse_date(request.GET.get('start_time'))
    end = _parse_date(request.GET.get('end_time'))

    if start:
        logs = logs.filter(start_time__date__gte=start.date())
    if end:
        logs = logs.filter(start_time__date__lte=end.date())

    logs = logs.order_by('-start_time')

    paginator = Paginator(logs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    default_hours = int(os.environ.get('BOTAPP_SILENT_BOT_THRESHOLD_HOURS', '24'))
    return render(request, 'botapp/bot_detail.html', {
        'bot': bot,
        'logs': page_obj,
        'page_obj': page_obj,
        'default_hours': default_hours,
    })

@login_required
def log_detail(request, log_id):
    log = get_object_or_404(TaskLog, id=log_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Se for uma requisição AJAX, retorna JSON
        data = {
            'id': log.id,
            'task': log.task.name,
            'description': log.task.description,
            'status': log.status,
            'start_time': log.start_time.strftime("%d/%m/%Y %H:%M") if log.start_time else None,
            'end_time': log.end_time.strftime("%d/%m/%Y %H:%M") if log.end_time else None,
            'duration': str(log.duration) if log.duration else None,
            'error_message': log.error_message,
            'exception_type': log.exception_type,
            'bot_dir': log.bot_dir,
            'os_platform': log.os_platform,
            'python_version': log.python_version,
            'host_ip': log.host_ip,
            'host_name': log.host_name,
            'user_login': log.user_login,
            'pid': log.pid,
            'manual_trigger': log.manual_trigger,
            'trigger_source': log.trigger_source,
            'env': log.env,
            'result_data': log.result_data,
        }
        return JsonResponse(data)
    else:
        # Se não for AJAX, renderiza o template completo
        context = {'log': log}
        return render(request, 'botapp/log_detail.html', context)


def _is_staff(u):
    return u.is_active and (u.is_superuser or u.is_staff)


# Service worker de auto-desregistro. Browsers que têm um SW antigo registrado
# continuam batendo em /sw.js; respondemos com um script que se desinstala e
# limpa o cache de SW para o origin. 200 ao invés de 404 para o browser efetivamente
# executar o unregister. Depois disso o request para de aparecer.
_SW_UNREGISTER_JS = (
    "self.addEventListener('install',function(e){self.skipWaiting();});"
    "self.addEventListener('activate',function(e){"
    "e.waitUntil(self.registration.unregister().then(function(){"
    "return self.clients.matchAll();}).then(function(cs){"
    "cs.forEach(function(c){c.navigate(c.url);});}));});"
)


def sw_js(_request):
    from django.http import HttpResponse
    resp = HttpResponse(_SW_UNREGISTER_JS, content_type='application/javascript')
    resp['Cache-Control'] = 'no-store, max-age=0'
    return resp


def favicon_ico(_request):
    from django.http import HttpResponse
    # 204 No Content — sem 404 no log, sem imagem servida. O <link rel="icon">
    # no base.html já cobre os browsers que respeitam a tag.
    return HttpResponse(status=204)


@require_POST
@user_passes_test(_is_staff, login_url='admin:login')
def cleanup_orphans_action(request):
    """Fecha logs started antigos como orphan_heartbeat. Aceita JSON.

    Body: {"threshold_hours": 24, "dry_run": false,
           "batch_size": 500, "sleep_ms": 100}

    Safety cap: request HTTP é limitado a BOTAPP_ORPHAN_HTTP_MAX (default 5000)
    linhas. Para volumes maiores, use `python manage.py cleanup_orphans` em um
    processo offline — a view avisa e retorna o total disponível.
    """
    from .management.commands.cleanup_orphans import cleanup_orphan_heartbeats
    from .models import TaskLog as _TaskLog
    from datetime import timedelta as _td

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'JSON inválido.'}, status=400)

    try:
        threshold = int(payload.get('threshold_hours', 24))
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'threshold_hours inválido.'}, status=400)

    if threshold < 1 or threshold > 24 * 365:
        return JsonResponse({'status': 'error', 'message': 'threshold_hours fora do intervalo [1, 8760].'}, status=400)

    dry = bool(payload.get('dry_run', False))

    # batch_size / sleep_ms opcionais — se ausentes, o default do command decide.
    raw_batch = payload.get('batch_size')
    raw_sleep = payload.get('sleep_ms')
    try:
        batch_size = int(raw_batch) if raw_batch not in (None, '') else None
        sleep_ms = int(raw_sleep) if raw_sleep not in (None, '') else None
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'batch_size/sleep_ms inválidos.'}, status=400)

    if batch_size is not None and not (50 <= batch_size <= 5000):
        return JsonResponse({'status': 'error', 'message': 'batch_size fora do intervalo [50, 5000].'}, status=400)
    if sleep_ms is not None and not (0 <= sleep_ms <= 5000):
        return JsonResponse({'status': 'error', 'message': 'sleep_ms fora do intervalo [0, 5000].'}, status=400)

    http_max = int(os.environ.get('BOTAPP_ORPHAN_HTTP_MAX', '5000'))

    if not dry:
        # Pré-checa volume — se for gigante, recusa antes de bloquear o worker HTTP.
        cutoff = timezone.now() - _td(hours=threshold)
        total_pending = _TaskLog.objects.filter(
            status=_TaskLog.Status.STARTED, start_time__lt=cutoff,
        ).count()
        if total_pending > http_max:
            return JsonResponse({
                'status': 'too_large',
                'count': total_pending,
                'http_max': http_max,
                'message': (
                    f'{total_pending} logs a limpar — acima do limite HTTP ({http_max}). '
                    f'Rode offline: python manage.py cleanup_orphans --threshold-hours {threshold} '
                    f'--batch-size 1000 --sleep-ms 50'
                ),
            }, status=413)

    try:
        count = cleanup_orphan_heartbeats(
            threshold, dry_run=dry, batch_size=batch_size, sleep_ms=sleep_ms,
        )
    except Exception:
        logger.exception('cleanup_orphans_action failed')
        return JsonResponse({'status': 'error', 'message': 'Falha interna.'}, status=500)

    logger.info(
        'cleanup_orphans_action user=%s threshold=%dh dry=%s batch=%s sleep_ms=%s count=%d',
        request.user, threshold, dry, batch_size, sleep_ms, count,
    )
    return JsonResponse({
        'status': 'success',
        'dry_run': dry,
        'threshold_hours': threshold,
        'batch_size': batch_size,
        'sleep_ms': sleep_ms,
        'count': count,
        'message': (f'{count} log(s) seriam marcados.' if dry
                    else f'{count} log(s) marcados como orphan_heartbeat.'),
    })


@require_POST
@user_passes_test(_is_staff, login_url='admin:login')
def bulk_set_silence_threshold(request):
    """Define threshold de silêncio em múltiplos bots de uma vez.

    Body:
      {"bot_ids": [1,2,3], "threshold_minutes": 10}   # granularidade fina
      {"bot_ids": [1,2,3], "threshold_hours": 12}     # retrocompat
      {"bot_ids": [1,2,3], "threshold_hours": null, "threshold_minutes": null}  # limpa tudo

    Precedência: minutes > hours. Quando um é setado, o outro é limpo para
    evitar configuração ambígua.
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'JSON inválido.'}, status=400)

    bot_ids = payload.get('bot_ids') or []
    if not isinstance(bot_ids, list) or not bot_ids:
        return JsonResponse({'status': 'error', 'message': 'bot_ids vazio.'}, status=400)

    try:
        bot_ids = [int(x) for x in bot_ids]
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'bot_ids deve ser lista de inteiros.'}, status=400)

    def _parse_positive(raw, field_name, max_value):
        if raw in (None, '', 'null'):
            return None
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'{field_name} inválido.')
        if v < 1 or v > max_value:
            raise ValueError(f'{field_name} fora do intervalo [1, {max_value}].')
        return v

    try:
        minutes = _parse_positive(payload.get('threshold_minutes'), 'threshold_minutes', 60 * 24 * 365)
        hours = _parse_positive(payload.get('threshold_hours'), 'threshold_hours', 24 * 365)
    except ValueError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    update_fields = {}
    if minutes is not None:
        update_fields['silence_threshold_minutes'] = minutes
        update_fields['silence_threshold_hours'] = None
        effective = f'{minutes}min'
    elif hours is not None:
        update_fields['silence_threshold_minutes'] = None
        update_fields['silence_threshold_hours'] = hours
        effective = f'{hours}h'
    else:
        # Ambos ausentes/null → limpa os dois (volta ao default global)
        update_fields['silence_threshold_minutes'] = None
        update_fields['silence_threshold_hours'] = None
        effective = 'default'

    count = Bot.objects.filter(id__in=bot_ids).update(**update_fields)

    logger.info(
        'bulk_set_silence_threshold user=%s count=%d threshold=%s',
        request.user, count, effective,
    )
    return JsonResponse({
        'status': 'success',
        'count': count,
        'threshold_minutes': minutes,
        'threshold_hours': hours,
        'effective': effective,
        'message': (f'{count} bot(s) voltaram ao default.' if effective == 'default'
                    else f'{count} bot(s) atualizado(s) com threshold={effective}.'),
    })


@login_required
@user_passes_test(_is_staff, login_url='admin:login')
def silence_thresholds_page(request):
    """Painel dedicado para configurar threshold de silêncio em lote.

    Filtros via GET: ?name=, ?department=, ?only_configured=1, ?only_missing=1.
    `only_configured` lista só bots com threshold customizado; `only_missing`
    mostra quem ainda está no default global (geralmente o que o admin quer
    auditar).
    """
    qs = Bot.objects.all().order_by('name')

    name = (request.GET.get('name') or '').strip()
    if name:
        qs = qs.filter(name__icontains=name)

    department = (request.GET.get('department') or '').strip()
    if department:
        qs = qs.filter(department__iexact=department)

    only_configured = request.GET.get('only_configured') == '1'
    only_missing = request.GET.get('only_missing') == '1'
    if only_configured:
        qs = qs.filter(
            Q(silence_threshold_minutes__isnull=False)
            | Q(silence_threshold_hours__isnull=False)
        )
    elif only_missing:
        qs = qs.filter(silence_threshold_minutes__isnull=True,
                       silence_threshold_hours__isnull=True)

    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get('page'))

    default_hours = int(os.environ.get('BOTAPP_SILENT_BOT_THRESHOLD_HOURS', '24'))

    return render(request, 'botapp/silence_thresholds.html', {
        'bots': page_obj,
        'page_obj': page_obj,
        'total_bots': paginator.count,
        'departments': _distinct_departments(),
        'default_hours': default_hours,
        'only_configured': only_configured,
        'only_missing': only_missing,
    })


@require_POST
@user_passes_test(lambda u: u.is_active and u.is_superuser, login_url='admin:login')
def toggle_bot_status(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id)
    bot.is_active = not bot.is_active
    bot.save()
    return JsonResponse({
        'status': 'success',
        'is_active': bot.is_active,
        'message': f'Bot {"ativado" if bot.is_active else "desativado"} com sucesso!'
    })


def _resolve_period(period, start_raw, end_raw):
    """Converte shortcut period ou datas cruas em (start_dt, end_dt). None = sem filtro."""
    start_dt = _parse_date(start_raw)
    end_dt = _parse_date(end_raw)
    if start_dt or end_dt or not period:
        return start_dt, end_dt
    now = datetime.now()
    if period == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if period == '7d':
        return now - timedelta(days=7), now
    if period == '30d':
        return now - timedelta(days=30), now
    if period == '90d':
        return now - timedelta(days=90), now
    return None, None  # 'all' ou desconhecido


def _p95_duration_seconds(logs_qs):
    """P50/P95 da duração (segundos). Postgres-nativo via percentile_cont.
    Retorna (None, None) em outros bancos ou se não houver dados."""
    if connection.vendor != 'postgresql':
        return None, None
    try:
        # Só logs completos com duração registrada.
        sql, params = logs_qs.filter(
            status=TaskLog.Status.COMPLETED, duration__isnull=False,
        ).query.sql_with_params()
        wrapped = (
            "SELECT "
            "EXTRACT(EPOCH FROM percentile_cont(0.50) WITHIN GROUP (ORDER BY sub.duration)), "
            "EXTRACT(EPOCH FROM percentile_cont(0.95) WITHIN GROUP (ORDER BY sub.duration)) "
            f"FROM ({sql}) sub"
        )
        with connection.cursor() as cursor:
            cursor.execute(wrapped, params)
            row = cursor.fetchone()
        p50, p95 = (row or (None, None))
        return (float(p50) if p50 is not None else None,
                float(p95) if p95 is not None else None)
    except Exception:
        logger.exception('dashboard: falha ao calcular p50/p95')
        return None, None


def _heatmap_matrix(logs_qs):
    """Matriz 7 (dias) × 24 (horas) com contagem de execuções."""
    rows = (
        logs_qs
        .annotate(wd=ExtractWeekDay('start_time'), hr=ExtractHour('start_time'))
        .values('wd', 'hr')
        .annotate(c=Count('id'))
    )
    # ExtractWeekDay: 1=Domingo..7=Sábado (MySQL/Postgres). Normaliza para 0..6 com seg=0.
    matrix = [[0] * 24 for _ in range(7)]
    for r in rows:
        wd, hr, c = r['wd'], r['hr'], r['c']
        if wd is None or hr is None:
            continue
        day_idx = ((int(wd) - 2) % 7)  # Seg=0, Ter=1, ..., Dom=6
        matrix[day_idx][int(hr)] = c
    return matrix


def _silent_bots_count(threshold_hours):
    """Bots ativos silenciosos há mais de `threshold_hours`."""
    cutoff = timezone.now() - timedelta(hours=threshold_hours)
    return Bot.objects.filter(is_active=True).filter(
        Q(last_execution_at__lt=cutoff) |
        Q(last_execution_at__isnull=True, created_at__lt=cutoff)
    ).count()


def _dashboard_aggregates(start_dt, end_dt):
    """Computa todos os agregados do dashboard. Resultado cacheável (pickle-safe)."""
    total_bots = Bot.objects.count()
    active_bots = Bot.objects.filter(is_active=True).count()
    inactive_bots = total_bots - active_bots

    bots_by_department = list(
        Bot.objects.values('department').annotate(count=Count('id')).order_by('-count')
    )

    logs_qs = TaskLog.objects.all()
    if start_dt:
        logs_qs = logs_qs.filter(start_time__date__gte=start_dt.date())
    if end_dt:
        logs_qs = logs_qs.filter(start_time__date__lte=end_dt.date())

    status_distribution = list(logs_qs.values('status').annotate(count=Count('id')))
    status_counts_map = {item['status']: item['count'] for item in status_distribution}

    execution_time = list(
        logs_qs.values('task__bot__name')
        .annotate(total_duration=Sum('duration'))
        .order_by('-total_duration')[:10]
    )

    # --- KPIs v2 ---
    total_runs = sum(status_counts_map.values())
    completed = status_counts_map.get(TaskLog.Status.COMPLETED, 0)
    failed = status_counts_map.get(TaskLog.Status.FAILED, 0)
    # 'started' são runs em andamento — não contam para success_rate.
    finished = completed + failed
    success_rate = (completed / finished * 100.0) if finished else None

    avg_duration = logs_qs.filter(
        status=TaskLog.Status.COMPLETED, duration__isnull=False,
    ).aggregate(avg=Avg('duration'))['avg']
    avg_duration_s = avg_duration.total_seconds() if avg_duration else None

    p50_s, p95_s = _p95_duration_seconds(logs_qs)

    # Top bots com mais falhas — inclui taxa de falha por bot.
    top_failing = list(
        logs_qs.values('task__bot__name')
        .annotate(
            fail=Count('id', filter=Q(status=TaskLog.Status.FAILED)),
            total=Count('id'),
        )
        .filter(fail__gt=0)
        .order_by('-fail')[:10]
    )
    top_failing_data = [
        {
            'name': r['task__bot__name'] or '(sem nome)',
            'fail': r['fail'],
            'total': r['total'],
            'rate': round(r['fail'] / r['total'] * 100.0, 1) if r['total'] else 0.0,
        }
        for r in top_failing
    ]

    silent_threshold = int(os.environ.get('BOTAPP_SILENT_BOT_THRESHOLD_HOURS', '24'))
    silent_bots = _silent_bots_count(silent_threshold)

    active_alerts = Alert.objects.filter(resolved_at__isnull=True).count()
    critical_alerts = Alert.objects.filter(
        resolved_at__isnull=True, severity=Alert.Severity.CRITICAL,
    ).count()

    heatmap = _heatmap_matrix(logs_qs)

    return {
        'total_bots': total_bots,
        'active_bots': active_bots,
        'inactive_bots': inactive_bots,
        'departments': [item['department'] or 'Sem Departamento' for item in bots_by_department],
        'department_counts': [item['count'] for item in bots_by_department],
        'status_labels': [item['status'] for item in status_distribution],
        'status_counts': [item['count'] for item in status_distribution],
        'bot_names': [item['task__bot__name'] for item in execution_time],
        'bot_durations': [
            item['total_duration'].total_seconds() / 3600 if item['total_duration'] else 0
            for item in execution_time
        ],
        # --- KPIs v2 (retrocompat: adicionado ao dict sem remover nada) ---
        'total_runs': total_runs,
        'completed_runs': completed,
        'failed_runs': failed,
        'success_rate': round(success_rate, 2) if success_rate is not None else None,
        'avg_duration_s': avg_duration_s,
        'p50_duration_s': p50_s,
        'p95_duration_s': p95_s,
        'top_failing': top_failing_data,
        'silent_bots': silent_bots,
        'silent_threshold_hours': silent_threshold,
        'active_alerts': active_alerts,
        'critical_alerts': critical_alerts,
        'heatmap': heatmap,
    }


@login_required
def dashboard(request):
    """Dashboard com filtros OPCIONAIS. Sem datas = todo o histórico.
    Atalho `period` aceita: today, 7d, 30d, 90d, all.
    Agregados são cacheados por (start, end) — TTL 60s; janela 'all' tem TTL maior."""
    start_raw = request.GET.get('start_date') or ''
    end_raw = request.GET.get('end_date') or ''
    period = request.GET.get('period') or ''

    start_dt, end_dt = _resolve_period(period, start_raw, end_raw)

    cache_key = f"botapp:dashboard:{start_dt.isoformat() if start_dt else 'none'}:{end_dt.isoformat() if end_dt else 'none'}"
    # 'Tudo' muda pouco a cada minuto (escala em anos/meses) — cache mais longo.
    ttl = 300 if (start_dt is None and end_dt is None) else 60

    data = cache.get(cache_key)
    if data is None:
        data = _dashboard_aggregates(start_dt, end_dt)
        cache.set(cache_key, data, timeout=ttl)

    context = {
        'total_bots': data['total_bots'],
        'active_bots': data['active_bots'],
        'inactive_bots': data['inactive_bots'],
        'departments_json': json.dumps(data['departments']),
        'department_counts_json': json.dumps(data['department_counts']),
        'status_labels_json': json.dumps(data['status_labels']),
        'status_counts_json': json.dumps(data['status_counts']),
        'bot_names_json': json.dumps(data['bot_names']),
        'bot_durations_json': json.dumps(data['bot_durations']),
        'start_date': start_raw,
        'end_date': end_raw,
        'period': period,
        'department_options': _distinct_departments(),
        # KPIs v2
        'total_runs': data['total_runs'],
        'completed_runs': data['completed_runs'],
        'failed_runs': data['failed_runs'],
        'success_rate': data['success_rate'],
        'avg_duration_s': data['avg_duration_s'],
        'p50_duration_s': data['p50_duration_s'],
        'p95_duration_s': data['p95_duration_s'],
        'top_failing': data['top_failing'],
        'silent_bots': data['silent_bots'],
        'silent_threshold_hours': data['silent_threshold_hours'],
        'active_alerts': data['active_alerts'],
        'critical_alerts': data['critical_alerts'],
        'heatmap_json': json.dumps(data['heatmap']),
    }
    return render(request, 'botapp/dashboard.html', context)


# ======================================================================
# Alerts
# ======================================================================
@login_required
def alert_list(request):
    """Lista alertas. Filtros: status (active|resolved|all), severity, type, bot.
    Sem datas por padrão — mostra todos os ativos. Paginação 25/página.
    """
    status = request.GET.get('status', 'active')
    severity = request.GET.get('severity')
    type_ = request.GET.get('type')
    bot_id = request.GET.get('bot')

    qs = Alert.objects.select_related('bot', 'acked_by', 'resolved_by')

    if status == 'active':
        qs = qs.filter(resolved_at__isnull=True)
    elif status == 'resolved':
        qs = qs.filter(resolved_at__isnull=False)
    # status == 'all' → sem filtro

    if severity:
        qs = qs.filter(severity=severity)
    if type_:
        qs = qs.filter(type=type_)
    if bot_id:
        qs = qs.filter(bot_id=bot_id)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'botapp/alerts.html', {
        'alerts': page_obj,
        'page_obj': page_obj,
        'total': paginator.count,
        'status': status,
        'severity': severity or '',
        'type': type_ or '',
        'bot_id': bot_id or '',
        'types': Alert.Type.choices,
        'severities': Alert.Severity.choices,
    })


@require_POST
@login_required
def alert_acknowledge(request, alert_id):
    alert = get_object_or_404(Alert, id=alert_id)
    if alert.acked_at is None:
        alert.acked_at = timezone.now()
        alert.acked_by = request.user
        alert.save(update_fields=['acked_at', 'acked_by', 'updated_at'])
    return JsonResponse({
        'status': 'ok',
        'acked_at': alert.acked_at.isoformat() if alert.acked_at else None,
        'acked_by': alert.acked_by.username if alert.acked_by_id else None,
    })


@require_POST
@login_required
def alert_resolve(request, alert_id):
    alert = get_object_or_404(Alert, id=alert_id)
    if alert.resolved_at is None:
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user
        if alert.acked_at is None:
            alert.acked_at = alert.resolved_at
            alert.acked_by = request.user
        alert.save(update_fields=[
            'resolved_at', 'resolved_by', 'acked_at', 'acked_by', 'updated_at',
        ])
    return JsonResponse({
        'status': 'ok',
        'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
    })


@login_required
def alerts_unread_count(request):
    """JSON: contagem de alertas ativos (não resolvidos). Usado pelo badge do sino.
    Cacheado por 10s para aguentar polling de múltiplas abas."""
    key = 'botapp:alerts:active_count'
    count = cache.get(key)
    if count is None:
        count = Alert.objects.filter(resolved_at__isnull=True).count()
        cache.set(key, count, timeout=10)
    return JsonResponse({'count': count})


# ======================================================================
# Explorador de execuções (tabela unificada + CSV stream)
# ======================================================================
EXPLORE_COLUMNS = [
    ('id', 'ID'),
    ('bot', 'Bot'),
    ('task', 'Task'),
    ('status', 'Status'),
    ('start_time', 'Início'),
    ('end_time', 'Fim'),
    ('duration', 'Duração'),
    ('exception_type', 'Exceção'),
    ('env', 'Ambiente'),
    ('host_name', 'Host'),
    ('os_platform', 'SO'),
    ('user_login', 'Usuário'),
    ('trigger_source', 'Trigger'),
    ('manual_trigger', 'Manual'),
]


def _explore_filter(request):
    """Aplica filtros comuns tanto ao HTML quanto ao CSV. Retorna queryset."""
    qs = TaskLog.objects.select_related('task', 'task__bot')

    bot_id = request.GET.get('bot')
    task_name = request.GET.get('task')
    status = request.GET.get('status')
    env = request.GET.get('env')
    host = request.GET.get('host')
    exc = request.GET.get('exception_type')
    manual = request.GET.get('manual_trigger')
    trigger = request.GET.get('trigger_source')
    start = _parse_date(request.GET.get('start_date'))
    end = _parse_date(request.GET.get('end_date'))
    q = request.GET.get('q')  # full-text sobre nome do bot/task

    if bot_id:
        qs = qs.filter(task__bot_id=bot_id)
    if task_name:
        qs = qs.filter(task__name__icontains=task_name)
    if status:
        qs = qs.filter(status=status)
    if env:
        qs = qs.filter(env__iexact=env)
    if host:
        qs = qs.filter(host_name__icontains=host)
    if exc:
        qs = qs.filter(exception_type__icontains=exc)
    if manual in ('true', 'false'):
        qs = qs.filter(manual_trigger=(manual == 'true'))
    if trigger:
        qs = qs.filter(trigger_source__iexact=trigger)
    if start:
        qs = qs.filter(start_time__date__gte=start.date())
    if end:
        qs = qs.filter(start_time__date__lte=end.date())
    if q:
        qs = qs.filter(Q(task__bot__name__icontains=q) | Q(task__name__icontains=q))

    return qs.order_by('-start_time')


@login_required
def explore(request):
    """Tabela unificada de execuções com filtros dinâmicos e paginação 50/página."""
    qs = _explore_filter(request)
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Opções para selects
    distinct_envs = list(
        TaskLog.objects.exclude(env__isnull=True).exclude(env__exact='')
        .values_list('env', flat=True).distinct().order_by('env')
    )
    bots = list(Bot.objects.values('id', 'name').order_by('name'))

    # Preserva a querystring para links de paginação/CSV sem o parâmetro page.
    qs_preserve = request.GET.copy()
    qs_preserve.pop('page', None)

    return render(request, 'botapp/explore.html', {
        'logs': page_obj,
        'page_obj': page_obj,
        'total': paginator.count,
        'envs': distinct_envs,
        'bots': bots,
        'columns': EXPLORE_COLUMNS,
        'querystring': qs_preserve.urlencode(),
    })


class _Echo:
    """File-like stub para csv.writer — retorna a string escrita."""
    def write(self, value):
        return value


def _iter_csv(qs):
    """Gera linhas CSV em streaming respeitando os select_related."""
    writer = csv.writer(_Echo())
    # BOM UTF-8 — Excel abre acentos corretamente.
    yield '\ufeff'
    header = [label for _, label in EXPLORE_COLUMNS]
    yield writer.writerow(header)

    # iterator() evita carregar todos os 1M+ logs na memória.
    # chunk_size=2000 balanceia round-trips vs uso de RAM.
    for log in qs.iterator(chunk_size=2000):
        yield writer.writerow([
            log.id,
            log.task.bot.name if log.task_id and log.task.bot_id else '',
            log.task.name if log.task_id else '',
            log.status,
            log.start_time.isoformat() if log.start_time else '',
            log.end_time.isoformat() if log.end_time else '',
            str(log.duration) if log.duration else '',
            log.exception_type or '',
            log.env or '',
            log.host_name or '',
            log.os_platform or '',
            log.user_login or '',
            log.trigger_source or '',
            'sim' if log.manual_trigger else 'nao',
        ])


@login_required
def explore_export_csv(request):
    """Export CSV streaming. Aceita os mesmos filtros de /explore/."""
    qs = _explore_filter(request)

    # Hard cap opcional — protege o servidor caso alguém peça todo o histórico.
    # Configurável via BOTAPP_CSV_MAX_ROWS. 0 = sem limite.
    max_rows = int(os.environ.get('BOTAPP_CSV_MAX_ROWS', '0'))
    if max_rows > 0:
        qs = qs[:max_rows]

    filename = f'botapp_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response = StreamingHttpResponse(_iter_csv(qs), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    # Desliga buffering em nginx/whitenoise para o browser receber chunks em streaming.
    response['X-Accel-Buffering'] = 'no'
    logger.info('explore.csv user=%s filters=%s', request.user, dict(request.GET))
    return response