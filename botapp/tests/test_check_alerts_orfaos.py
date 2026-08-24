"""Execução presa em `started` para sempre tem de ser encerrada.

O `@task` fecha o TaskLog no `finally` — inclusive quando a task levanta
exceção. Log que fica em `started` indefinidamente significa que o PROCESSO
morreu sem passar pelo finally: container derrubado, OOM, `compose down`, runner
cancelado. Medido em 24/08/2026: 9 bots com 47 execuções assim, a mais antiga de
4 dias, uma delas com 30 registros do mesmo bot. Enquanto ficam abertas, o
heartbeat_lost daquele bot nunca se resolve e, pela deduplicação, tampa o
próximo alerta do mesmo tipo.

A janela entre o limiar do heartbeat (6h) e o do órfão (24h) é de propósito: ali
o alerta DEVE aparecer, porque pode ser job de verdade travado.
"""
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from botapp.models import Alert, Bot, Task, TaskLog


class BaseOrfaos(TestCase):
    def bot(self, nome='bot-x'):
        return Bot.objects.create(name=nome, version='1')

    def log(self, bot, horas, status=TaskLog.Status.STARTED, fim=None):
        tarefa = Task.objects.create(bot=bot, name=f'tarefa-{horas}')
        return TaskLog.objects.create(
            task=tarefa, status=status,
            start_time=timezone.now() - timedelta(hours=horas),
            end_time=fim)

    def rodar(self):
        call_command('check_alerts', '--no-notify', verbosity=0)


class TestFechamentoDeOrfaos(BaseOrfaos):
    def test_fecha_execucao_presa_ha_mais_de_24h(self):
        registro = self.log(self.bot(), horas=30)

        self.rodar()

        registro.refresh_from_db()
        self.assertEqual(registro.status, TaskLog.Status.FAILED)
        self.assertEqual(registro.exception_type, 'ProcessoMorto')
        self.assertIn('sem passar pelo finally', registro.error_message)

    def test_nao_fecha_execucao_de_8h(self):
        """Entre 6h e 24h o heartbeat_lost deve aparecer: pode ser job travado."""
        registro = self.log(self.bot(), horas=8)

        self.rodar()

        registro.refresh_from_db()
        self.assertEqual(registro.status, TaskLog.Status.STARTED)

    def test_nao_toca_no_que_ja_terminou(self):
        agora = timezone.now()
        registro = self.log(self.bot(), horas=30,
                            status=TaskLog.Status.COMPLETED, fim=agora)

        self.rodar()

        registro.refresh_from_db()
        self.assertEqual(registro.status, TaskLog.Status.COMPLETED)

    def test_end_time_fica_nulo_porque_a_hora_da_morte_e_desconhecida(self):
        """Marcar `now` inflaria a duracao com o tempo que o registro ficou orfao."""
        registro = self.log(self.bot(), horas=30)

        self.rodar()

        registro.refresh_from_db()
        self.assertIsNone(registro.end_time)

    def test_fechar_orfao_resolve_o_heartbeat_lost_do_bot(self):
        """O ciclo completo: fecha o orfao e o alerta sai do painel."""
        bot = self.bot()
        self.log(bot, horas=30)
        alerta = Alert.objects.create(
            bot=bot, type=Alert.Type.HEARTBEAT_LOST,
            severity=Alert.Severity.MEDIUM, message='travado')

        self.rodar()

        alerta.refresh_from_db()
        self.assertIsNotNone(alerta.resolved_at)

    def test_dry_run_nao_fecha_orfao(self):
        registro = self.log(self.bot(), horas=30)

        call_command('check_alerts', '--dry-run', verbosity=0)

        registro.refresh_from_db()
        self.assertEqual(registro.status, TaskLog.Status.STARTED)

    def test_limiar_configuravel_por_ambiente(self):
        import os
        registro = self.log(self.bot(), horas=10)
        os.environ['BOTAPP_ORPHAN_TASKLOG_HOURS'] = '9'
        try:
            self.rodar()
        finally:
            os.environ.pop('BOTAPP_ORPHAN_TASKLOG_HOURS', None)

        registro.refresh_from_db()
        self.assertEqual(registro.status, TaskLog.Status.FAILED)
