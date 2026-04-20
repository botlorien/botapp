# botapp/rest_views.py

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Bot, Task, TaskLog
from .serializers import BotSerializer, TaskSerializer, TaskLogSerializer


class SDKReadWritePermission(permissions.BasePermission):
    """Permissão desenhada para o padrão de uso dos SDKs (Python e Go).

    Os RPAs em produção fazem apenas GET/POST/PATCH nos endpoints — nunca
    DELETE nem PUT. Bloquear os dois primeiros fecha o vetor de apagar ou
    sobrescrever histórico sem afetar nenhum cliente existente. Operações
    destrutivas ficam restritas a usuários staff (admins do dashboard).
    """

    SAFE_SDK_METHODS = {'GET', 'HEAD', 'OPTIONS', 'POST', 'PATCH'}

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in self.SAFE_SDK_METHODS:
            return True
        return bool(request.user.is_staff)


class BotViewSet(viewsets.ModelViewSet):
    queryset = Bot.objects.all()
    serializer_class = BotSerializer
    permission_classes = [SDKReadWritePermission]

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


class TaskLogViewSet(viewsets.ModelViewSet):
    queryset = TaskLog.objects.all()
    serializer_class = TaskLogSerializer
    permission_classes = [SDKReadWritePermission]
