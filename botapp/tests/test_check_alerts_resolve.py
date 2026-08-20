"""Alerta de bot tem de FECHAR quando a condição passa.

`check_alerts` só deduplicava contra alerta aberto — nenhuma das quatro regras
fechava o que criou. Consequência medida em 20/08/2026: o painel acumula alerta
de bot que já voltou ao normal, e a única saída é alguém clicar "resolver" em
cada um. Alerta que não fecha treina o operador a ignorar o painel.

Nada de dado real aqui: o pacote é público.
"""
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from botapp.models import Alert, Bot, Task, TaskLog


class BaseAlertas(TestCase):
    def bot(self, nome='bot-x', **extra):
        return Bot.objects.create(name=nome, version='1', **extra)

    def tarefa(self, bot, nome='tarefa', **extra):
        return Task.objects.create(bot=bot, name=nome, **extra)

    def alerta(self, bot, tipo, **extra):
        return Alert.objects.create(
            bot=bot, type=tipo, severity=Alert.Severity.MEDIUM,
            message='condição observada no passado', **extra)

    def rodar(self):
        call_command('check_alerts', '--no-notify', verbosity=0)


class TestSilentBot(BaseAlertas):
    def test_fecha_quando_o_bot_volta_a_executar(self):
        bot = self.bot()
        alerta = self.alerta(bot, Alert.Type.SILENT_BOT)
        Bot.objects.filter(pk=bot.pk).update(last_execution_at=timezone.now())

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)
        self.assertEqual(alerta.payload.get('fechado_por'), 'condicao_superada')

    def test_nao_fecha_bot_ainda_silencioso(self):
        """Fechar cedo é pior que não fechar: esconde bot realmente parado."""
        bot = self.bot()
        alerta = self.alerta(bot, Alert.Type.SILENT_BOT)
        Bot.objects.filter(pk=bot.pk).update(
            last_execution_at=timezone.now() - timedelta(days=3))

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNone(alerta.resolved_at)


class TestHeartbeatLost(BaseAlertas):
    def _log_travado(self, tarefa, horas):
        return TaskLog.objects.create(
            task=tarefa, status=TaskLog.Status.STARTED,
            start_time=timezone.now() - timedelta(hours=horas))

    def test_fecha_quando_nao_ha_mais_execucao_travada(self):
        bot = self.bot()
        tarefa = self.tarefa(bot)
        travado = self._log_travado(tarefa, 9)
        alerta = self.alerta(bot, Alert.Type.HEARTBEAT_LOST)
        # a execução foi encerrada (como acontece ao fechar o registro órfão)
        TaskLog.objects.filter(pk=travado.pk).update(
            status=TaskLog.Status.FAILED)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)

    def test_nao_fecha_com_execucao_ainda_travada(self):
        bot = self.bot()
        tarefa = self.tarefa(bot)
        self._log_travado(tarefa, 9)
        alerta = self.alerta(bot, Alert.Type.HEARTBEAT_LOST)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNone(alerta.resolved_at)

    def test_execucao_recente_em_started_nao_conta_como_travada(self):
        """Job longo em andamento não é heartbeat perdido."""
        bot = self.bot()
        tarefa = self.tarefa(bot)
        self._log_travado(tarefa, 1)          # 1h < threshold de 6h
        alerta = self.alerta(bot, Alert.Type.HEARTBEAT_LOST)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)


class TestErrorSpike(BaseAlertas):
    def _falhas(self, tarefa, quantas, minutos_atras):
        for _ in range(quantas):
            TaskLog.objects.create(
                task=tarefa, status=TaskLog.Status.FAILED,
                start_time=timezone.now() - timedelta(minutes=minutos_atras))

    def test_fecha_quando_a_janela_passa(self):
        bot = self.bot()
        tarefa = self.tarefa(bot)
        self._falhas(tarefa, 6, minutos_atras=180)   # fora da janela de 60min
        alerta = self.alerta(bot, Alert.Type.ERROR_SPIKE)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)

    def test_nao_fecha_com_pico_ainda_dentro_da_janela(self):
        bot = self.bot()
        tarefa = self.tarefa(bot)
        self._falhas(tarefa, 6, minutos_atras=5)
        alerta = self.alerta(bot, Alert.Type.ERROR_SPIKE)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNone(alerta.resolved_at)


class TestDuracao(BaseAlertas):
    def test_fecha_quando_a_duracao_volta_ao_esperado(self):
        bot = self.bot()
        tarefa = self.tarefa(bot, expected_duration_seconds=100)
        for _ in range(8):
            TaskLog.objects.create(
                task=tarefa, status=TaskLog.Status.COMPLETED,
                start_time=timezone.now(), duration=timedelta(seconds=90))
        alerta = self.alerta(bot, Alert.Type.DURATION_REGRESSION)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)

    def test_nao_fecha_com_duracao_ainda_alta(self):
        bot = self.bot()
        tarefa = self.tarefa(bot, expected_duration_seconds=100)
        for _ in range(8):
            TaskLog.objects.create(
                task=tarefa, status=TaskLog.Status.COMPLETED,
                start_time=timezone.now(), duration=timedelta(seconds=400))
        alerta = self.alerta(bot, Alert.Type.DURATION_REGRESSION)

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNone(alerta.resolved_at)


class TestDryRunNaoEscreve(BaseAlertas):
    def test_dry_run_nao_fecha_nada(self):
        bot = self.bot()
        alerta = self.alerta(bot, Alert.Type.SILENT_BOT)
        Bot.objects.filter(pk=bot.pk).update(last_execution_at=timezone.now())

        call_command('check_alerts', '--dry-run', verbosity=0)

        alerta.refresh_from_db()
        self.assertIsNone(alerta.resolved_at)
