"""Limiar de silent_bot para bot que não roda todo dia.

Caso real (12/09/2026): um bot de relatório diário roda `0 10 * * 1-5`.
Sexta às 10h ele rodou; sábado às 15h46 o detector abriu
"sem execução há 25h" — o fim de semana inteiro é silêncio PREVISTO pelo
próprio agendamento. Pior que o ruído: alerta falso ABERTO cala a próxima
ocorrência (a deduplicação é contra alerta ABERTO do mesmo tipo), então a
segunda-feira sem execução — essa sim real — não abriria alerta nenhum.

A regra nunca fica mais AGRESSIVA que o limiar global: o cron só é usado
quando prevê um vão MAIOR. Bot horário parado continua sendo julgado pelas
mesmas 25h de sempre, e não vira alerta a cada duas horas.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from botapp.management.commands.check_alerts import Command, _threshold_silencio
from botapp.models import Alert, Bot, CIConnection, CIProject


class BaseSilencio(TestCase):
    def bot(self, nome, silencio_horas, **kwargs):
        b = Bot.objects.create(name=nome, description='', version='1', **kwargs)
        Bot.objects.filter(pk=b.pk).update(
            last_execution_at=timezone.now() - timedelta(hours=silencio_horas))
        b.refresh_from_db()
        return b

    def com_cron(self, bot, cron):
        conexao = CIConnection.objects.create(
            name='gitlab', base_url='https://exemplo.invalid',
            namespace='grupo-x', token_source='env',
            token_env_var='BOTAPP_CI_TOKEN')
        projeto = CIProject.objects.create(
            connection=conexao, external_id=1, path='g/p', name='p', bot=bot)
        projeto.schedules.create(external_id=1, cron=cron, active=True)
        return bot

    def detectar(self, horas_default=25):
        return Command()._detect_silent(timezone.now(), horas_default, dry=False)


class TestThresholdPeloCron(BaseSilencio):
    def test_dias_uteis_toleram_o_fim_de_semana(self):
        bot = self.com_cron(self.bot('dias uteis', 30), '0 10 * * 1-5')
        self.assertEqual(_threshold_silencio(bot, 25), 73 * 3600)

    def test_override_manual_manda(self):
        """Quem escreveu o número no bot sabia o que queria."""
        bot = self.com_cron(
            self.bot('com override', 30, silence_threshold_hours=25),
            '0 10 * * 1-5')
        self.assertEqual(_threshold_silencio(bot, 25), 25 * 3600)

    def test_cron_curto_nao_deixa_o_limiar_mais_agressivo(self):
        """Bot horário continua julgado pelas 25h globais, não por 2h."""
        bot = self.com_cron(self.bot('horario', 30), '0 * * * *')
        self.assertEqual(_threshold_silencio(bot, 25), 25 * 3600)

    def test_bot_sem_projeto_de_ci_usa_o_default(self):
        bot = self.bot('sem ci', 30)
        self.assertEqual(_threshold_silencio(bot, 25), 25 * 3600)

    def test_agendamento_inativo_nao_conta(self):
        bot = self.bot('desligado', 30)
        conexao = CIConnection.objects.create(
            name='gitlab', base_url='https://exemplo.invalid',
            namespace='grupo-x', token_source='env',
            token_env_var='BOTAPP_CI_TOKEN')
        projeto = CIProject.objects.create(
            connection=conexao, external_id=1, path='g/p', name='p', bot=bot)
        projeto.schedules.create(external_id=1, cron='0 10 * * 1-5', active=False)
        self.assertEqual(_threshold_silencio(bot, 25), 25 * 3600)


class TestDeteccaoComCron(BaseSilencio):
    def test_fim_de_semana_nao_abre_alerta(self):
        self.com_cron(self.bot('dias uteis', 30), '0 10 * * 1-5')
        self.assertEqual(self.detectar(), [])
        self.assertFalse(Alert.objects.filter(type=Alert.Type.SILENT_BOT).exists())

    def test_silencio_alem_do_vao_previsto_abre_alerta(self):
        """A segunda-feira que não rodou continua sendo alerta."""
        self.com_cron(self.bot('dias uteis', 80), '0 10 * * 1-5')
        self.assertEqual(len(self.detectar()), 1)
        alerta = Alert.objects.get(type=Alert.Type.SILENT_BOT)
        self.assertEqual(alerta.payload['threshold_seconds'], 73 * 3600)

    def test_bot_sem_ci_continua_alertando_em_25h(self):
        self.bot('residente', 30)
        self.assertEqual(len(self.detectar()), 1)


class TestResolucaoComCron(BaseSilencio):
    """O resolvedor precisa do MESMO limiar, senão o alerta nunca fecha."""

    def test_alerta_fecha_quando_o_bot_esta_dentro_do_vao_do_cron(self):
        bot = self.com_cron(self.bot('dias uteis', 30), '0 10 * * 1-5')
        alerta = Alert.objects.create(
            bot=bot, type=Alert.Type.SILENT_BOT,
            severity=Alert.Severity.MEDIUM, message='sem execução')

        superada = Command()._condicao_superada(
            alerta, bot, timezone.now(), 25, 60, 5, 6, 20, 1.5)

        self.assertTrue(superada)

    def test_alerta_nao_fecha_com_silencio_alem_do_vao(self):
        bot = self.com_cron(self.bot('dias uteis', 80), '0 10 * * 1-5')
        alerta = Alert.objects.create(
            bot=bot, type=Alert.Type.SILENT_BOT,
            severity=Alert.Severity.MEDIUM, message='sem execução')

        superada = Command()._condicao_superada(
            alerta, bot, timezone.now(), 25, 60, 5, 6, 20, 1.5)

        self.assertFalse(superada)
