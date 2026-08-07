# botapp/rest_views.py

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Bot, Task, TaskLog
from .serializers import BotSerializer, TaskSerializer, TaskLogSerializer
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
