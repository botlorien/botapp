# botapp/rest_views.py

from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.authentication import BasicAuthentication, TokenAuthentication
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from .models import Alert, Bot, Task, TaskLog
from .serializers import (
    AlertIngestSerializer,
    BotSerializer,
    TaskSerializer,
    TaskLogSerializer,
)
from . import scoping


class SDKReadWritePermission(permissions.BasePermission):
    """Permissão desenhada para o padrão de uso dos SDKs (Python e Go).

    Os RPAs em produção fazem apenas GET/POST/PATCH nos endpoints (nunca PUT/
    DELETE) e autenticam por Token/Basic (headless, NÃO por sessão).

    - Leitura (GET/HEAD/OPTIONS): qualquer autenticado — o get_queryset já filtra
      por departamento no caso de sessão de navegador.
    - Escrita SDK (POST/PATCH): só clientes SDK (Token/Basic) OU staff. Sessões de
      navegador NÃO escrevem pela API — evita que um usuário escopado crie/edite
      bots pela API browsable, contornando o gate da UI. Automações (Basic/Token)
      seguem inalteradas.
    - PUT/DELETE (destrutivo): só staff.
    """

    LEITURA = {'GET', 'HEAD', 'OPTIONS'}
    ESCRITA_SDK = {'POST', 'PATCH'}

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in self.LEITURA:
            return True
        if request.method in self.ESCRITA_SDK:
            # SDK headless (não-sessão) OU staff; sessão de navegador comum → nega.
            return (not scoping.autenticado_por_sessao(request)) or bool(u.is_staff)
        return bool(u.is_staff)  # PUT/DELETE


class BotViewSet(viewsets.ModelViewSet):
    queryset = Bot.objects.all()
    serializer_class = BotSerializer
    permission_classes = [SDKReadWritePermission]

    def get_queryset(self):
        # Escopo por departamento só para sessão de navegador; SDK (Token/Basic)
        # vê tudo (precisa registrar bots de qualquer depto).
        qs = super().get_queryset()
        deps = scoping.escopo_api(self.request)
        return qs.filter(department__in=deps) if deps is not None else qs

    @action(detail=True, methods=["get"])
    def tasks(self, request, pk=None):
        bot = self.get_object()
        tasks = bot.tasks.all()
        serializer = TaskSerializer(tasks, many=True)
        return Response(serializer.data)


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [SDKReadWritePermission]

    def get_queryset(self):
        qs = super().get_queryset()
        deps = scoping.escopo_api(self.request)
        return qs.filter(bot__department__in=deps) if deps is not None else qs


class TaskLogViewSet(viewsets.ModelViewSet):
    queryset = TaskLog.objects.all()
    serializer_class = TaskLogSerializer
    permission_classes = [SDKReadWritePermission]

    def get_queryset(self):
        qs = super().get_queryset()
        deps = scoping.escopo_api(self.request)
        return qs.filter(task__bot__department__in=deps) if deps is not None else qs


_SEVERITY_ALIASES = {
    # convenções comuns de monitores → enum do Alert
    'critical': 'critical', 'crit': 'critical', 'page': 'critical', 'fatal': 'critical',
    'critico': 'critical', 'crítico': 'critical', 'emergency': 'critical',
    'high': 'high', 'error': 'high', 'err': 'high', 'major': 'high',
    'warning': 'high', 'warn': 'high', 'aviso': 'high',
    'medium': 'medium', 'moderate': 'medium', 'minor': 'medium',
    'low': 'low', 'info': 'low', 'information': 'low', 'notice': 'low', 'none': 'low',
}


def _normalize_severity(value):
    """Mapeia a severidade de um monitor externo para o enum do Alert (default medium)."""
    if not value:
        return Alert.Severity.MEDIUM
    return _SEVERITY_ALIASES.get(str(value).strip().lower(), Alert.Severity.MEDIUM)


def _normalize_external_item(raw):
    """Converte um alerta no formato Grafana/Alertmanager para o shape genérico.

    Um item do webhook do Grafana/Alertmanager traz `labels`/`annotations` em vez
    de `type`/`message`. Detecta esse formato (tem labels/annotations e não tem
    `type`) e traduz: `type` ← labels.type|alertname, `severity` ← labels.severity
    (normalizada), `message` ← annotations.summary|description, `fingerprint` ←
    fingerprint, `status` ← status; o resto vira `payload` (contexto). Itens já no
    shape genérico passam intactos.
    """
    if not isinstance(raw, dict):
        return raw
    labels = raw.get('labels')
    annotations = raw.get('annotations')
    if 'type' in raw or not (isinstance(labels, dict) or isinstance(annotations, dict)):
        return raw  # já é o shape genérico

    labels = labels if isinstance(labels, dict) else {}
    annotations = annotations if isinstance(annotations, dict) else {}
    tipo = (labels.get('type') or labels.get('alertname') or 'external')[:30]
    message = (annotations.get('summary') or annotations.get('description')
               or labels.get('alertname') or '(sem mensagem)')
    payload = {'labels': labels, 'annotations': annotations}
    for k in ('startsAt', 'endsAt', 'generatorURL', 'valueString', 'values',
              'dashboardURL', 'panelURL', 'silenceURL'):
        if raw.get(k):
            payload[k] = raw[k]
    return {
        'status': raw.get('status') or 'firing',
        'type': tipo,
        'severity': _normalize_severity(labels.get('severity')),
        'message': message,
        'fingerprint': raw.get('fingerprint') or '',
        'payload': payload,
    }


def _active_alert_qs(tipo, fingerprint, message):
    """Alertas ativos (não resolvidos) que casam com este item de ingest.

    Chave de dedup, na ordem de preferência do emissor: `fingerprint` (estável,
    o que o Grafana/Alertmanager fornece por alerta) guardado em
    `payload.fingerprint`; se ausente, cai para `type` + `message` idênticos.
    Espelha a convenção interna 'um alerta ativo por chave' (índice
    alert_bot_type_res_idx / padrão payload__project_id do ci_sync).
    """
    qs = Alert.objects.filter(type=tipo, resolved_at__isnull=True)
    if fingerprint:
        return qs.filter(payload__fingerprint=fingerprint)
    return qs.filter(message=message)


@api_view(['POST'])
@authentication_classes([TokenAuthentication, BasicAuthentication])
@permission_classes([permissions.IsAuthenticated])
def alert_ingest(request):
    """Ingest de alertas de monitores externos (ex.: webhook do Grafana).

    Endpoint máquina-a-máquina: autentica por Token DRF (`Authorization: Token
    <chave>`) ou Basic — nunca por sessão de navegador (sem SessionAuthentication,
    logo isento de CSRF). Aceita um único alerta OU um lote em `{"alerts": [...]}`,
    para casar com um webhook que agrupa vários alertas por notificação.

    Cada item: `type` (str), `message` (str), `severity` (low|medium|high|
    critical, default medium), `status` (firing|resolved, default firing),
    `fingerprint` (chave de dedup, opcional), `bot_name` (associa a um Bot se
    existir, opcional) e `payload` (objeto de contexto livre, opcional).

    Também aceita o formato nativo do webhook do Grafana/Alertmanager (itens com
    `labels`/`annotations`): são traduzidos para o shape acima automaticamente
    (`type` ← labels.type|alertname, `severity` normalizada de
    critical/warning/info/critico/aviso/…, `message` ← annotations.summary), então
    o Grafana só precisa apontar o webhook para cá com o header de auth — sem
    template de payload.

    `firing` cria o alerta se não houver um ativo com a mesma chave (idempotente:
    o Grafana reenvia enquanto a condição persiste). `resolved` fecha os alertas
    ativos que casam com a chave. Não dispara notificações (Slack/Discord/e-mail):
    o alerta aparecer no painel É a entrega.
    """
    body = request.data
    if isinstance(body, dict) and 'alerts' in body:
        items = body.get('alerts') or []
    elif isinstance(body, list):
        items = body
    else:
        items = [body]

    if not isinstance(items, list):
        return Response(
            {'ok': False, 'detail': "'alerts' deve ser uma lista."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(items) > 500:
        return Response(
            {'ok': False, 'detail': 'no máximo 500 alertas por requisição.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    created = resolved = deduped = 0
    errors = []
    for i, raw in enumerate(items):
        raw = _normalize_external_item(raw)
        ser = AlertIngestSerializer(data=raw if isinstance(raw, dict) else {})
        if not ser.is_valid():
            errors.append({'index': i, 'errors': ser.errors})
            continue
        d = ser.validated_data
        fingerprint = (d.get('fingerprint') or '').strip()
        payload = dict(d.get('payload') or {})
        if fingerprint:
            payload['fingerprint'] = fingerprint

        bot = None
        bot_name = (d.get('bot_name') or '').strip()
        if bot_name:
            bot = Bot.objects.filter(name=bot_name).first()

        match = _active_alert_qs(d['type'], fingerprint, d['message'])

        if d.get('status') == 'resolved':
            n = match.update(resolved_at=timezone.now())
            resolved += n
            continue

        if match.exists():
            deduped += 1
            continue

        Alert.objects.create(
            type=d['type'],
            severity=d.get('severity', Alert.Severity.MEDIUM),
            bot=bot,
            message=d['message'],
            payload=payload or None,
        )
        created += 1

    resp = {
        'ok': not errors,
        'created': created,
        'resolved': resolved,
        'deduped': deduped,
    }
    if errors:
        resp['errors'] = errors
    return Response(
        resp,
        status=status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK,
    )
