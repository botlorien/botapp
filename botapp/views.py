from django.shortcuts import render, get_object_or_404
from .models import Bot, TaskLog
from datetime import datetime
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.contrib.auth.decorators import user_passes_test
from datetime import datetime, timedelta
import json

@login_required
def filter_bots(request):
    bots = Bot.objects.all()

    name = request.GET.get("name")
    department = request.GET.get("department")
    is_active = request.GET.get('is_active')
    last_status = request.GET.get('last_status')
    os_platform = request.GET.get("os_platform")
    start = request.GET.get("start")
    end = request.GET.get("end")

    if name:
        bots = bots.filter(name__icontains=name)

    if department:
        bots = bots.filter(department__icontains=department)

    if is_active in ["true", "false"]:
        bots = bots.filter(is_active=(is_active == "true"))

    if os_platform or start or end:
        logs = TaskLog.objects.filter(task__bot__in=bots)

        if os_platform:
            logs = logs.filter(os_platform__icontains=os_platform)

        if start and end:
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d")
                end_date = datetime.strptime(end, "%Y-%m-%d")

                # Caso as datas sejam iguais, ajusta o intervalo para o dia inteiro
                if start_date == end_date:
                    logs = logs.filter(start_time__date=start_date)
                else:
                    logs = logs.filter(start_time__date__gte=start_date, end_time__date__lte=end_date)
            except ValueError:
                pass
        elif start:
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d")
                logs = logs.filter(start_time__date__gte=start_date)
            except ValueError:
                pass
        elif end:
            try:
                end_date = datetime.strptime(end, "%Y-%m-%d")
                logs = logs.filter(end_time__date__lte=end_date)
            except ValueError:
                pass

        # filtra os bots com base nos logs encontrados
        bot_ids = logs.values_list("task__bot_id", flat=True).distinct()
        bots = bots.filter(id__in=bot_ids)

        # Último log e filtro por status de execução
    filtered_bots = []
    for bot in bots:
        last_log = TaskLog.objects.filter(task__bot=bot).order_by('-start_time').first()
        bot.latest_status = last_log.status if last_log else None

        if last_status:
            if bot.latest_status == last_status:
                filtered_bots.append(bot)
        else:
            filtered_bots.append(bot)

    return filtered_bots

@login_required
def bot_list(request):
    bots = filter_bots(request)
    return render(request, "botapp/bot_list.html", {"bots": bots})

@login_required
def bot_detail(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id)
    logs = TaskLog.objects.filter(task__bot=bot)

    start = request.GET.get('start_time')
    end = request.GET.get('end_time')

    if start and end:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")

            # Caso as datas sejam iguais, ajusta o intervalo para o dia inteiro
            if start_date == end_date:
                logs = logs.filter(start_time__date=start_date)
            else:
                logs = logs.filter(start_time__date__gte=start_date, end_time__date__lte=end_date)
        except ValueError:
            pass
    elif start:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            logs = logs.filter(start_time__date__gte=start_date)
        except ValueError:
            pass
    elif end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d")
            logs = logs.filter(end_time__date__lte=end_date)
        except ValueError:
            pass

    logs = logs.order_by('-start_time')

    # Paginação
    paginator = Paginator(logs, 25)  # Mostra 25 logs por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'botapp/bot_detail.html', {
        'bot': bot,
        'logs': page_obj,
        'page_obj': page_obj  # Para acessar métodos de paginação no template
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


@login_required
def dashboard(request):
    # Filtros de período (apenas para dados dinâmicos)
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    # Definir período padrão (últimos 30 dias)
    if not start_date or not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    # Converter para objetos datetime
    try:
        start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
    except:
        start_datetime = datetime.now() - timedelta(days=30)
        end_datetime = datetime.now()
    
    # Dados FIXOS (não são afetados pelos filtros)
    total_bots = Bot.objects.count()
    active_bots = Bot.objects.filter(is_active=True).count()
    inactive_bots = Bot.objects.filter(is_active=False).count()
    bots_by_department = Bot.objects.values('department').annotate(count=Count('id')).order_by('-count')
    
    # Dados DINÂMICOS (afetados pelos filtros de período)
    status_distribution = TaskLog.objects.filter(
        start_time__date__gte=start_datetime,
        start_time__date__lte=end_datetime
    ).values('status').annotate(count=Count('id'))
    
    execution_time = TaskLog.objects.filter(
        start_time__date__gte=start_datetime,
        start_time__date__lte=end_datetime
    ).values('task__bot__name').annotate(
        total_duration=Sum('duration')
    ).order_by('-total_duration')[:10]
    
    # Preparar dados para gráficos
    departments = [item['department'] or 'Sem Departamento' for item in bots_by_department]
    department_counts = [item['count'] for item in bots_by_department]
    
    status_labels = [item['status'] for item in status_distribution]
    status_counts = [item['count'] for item in status_distribution]
    
    bot_names = [item['task__bot__name'] for item in execution_time]
    bot_durations = [item['total_duration'].total_seconds()/3600 if item['total_duration'] else 0 for item in execution_time]
    
    context = {
        # Dados FIXOS
        'total_bots': total_bots,
        'active_bots': active_bots,
        'inactive_bots': inactive_bots,
        'departments_json': json.dumps(departments),
        'department_counts_json': json.dumps(department_counts),
        
        # Dados DINÂMICOS
        'status_labels_json': json.dumps(status_labels),
        'status_counts_json': json.dumps(status_counts),
        'bot_names_json': json.dumps(bot_names),
        'bot_durations_json': json.dumps(bot_durations),
        'start_date': start_date,
        'end_date': end_date,
    }
    
    return render(request, 'botapp/dashboard.html', context)