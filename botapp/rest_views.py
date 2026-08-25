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
