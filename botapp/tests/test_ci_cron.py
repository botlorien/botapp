"""Estimativa de intervalo do cron — o que decide o limiar de schedule_without_run.

Alerta #907 (05/09/2026): `carvalima-group/bot_create_bitrix_comercial_activity`
tem agendamento MENSAL (`0 6 15 * *`, dia 15 às 06:00) e rodou normalmente em
15/08. O estimador não reconhecia dia-do-mês fixo e caía no fallback semanal,
então o limiar virou 7d × 3 = 21d = as "504h sem execução" do alerta — sobre um
bot que estava em dia e cuja próxima execução era 15/09.

O estimador não precisa ser um parser de cron completo; precisa é NÃO subestimar
o intervalo, porque subestimar gera alerta falso, e alerta falso aberto cega a
próxima ocorrência real (a deduplicação é contra alerta ABERTO do mesmo tipo).
"""
from datetime import timedelta

from django.test import SimpleTestCase

from botapp.ci_sync import _intervalo_estimado


class TestIntervaloEstimado(SimpleTestCase):
    def test_cron_mensal_por_dia_do_mes(self):
        """`0 6 15 * *` = uma vez por mês, não uma vez por semana."""
        self.assertEqual(_intervalo_estimado('0 6 15 * *'), timedelta(days=31))

    def test_cron_mensal_com_varios_dias_do_mes(self):
        """`0 6 1,15 * *` = quinzenal."""
        self.assertEqual(_intervalo_estimado('0 6 1,15 * *'), timedelta(days=15))

    def test_cron_anual_por_mes_fixo(self):
        self.assertEqual(_intervalo_estimado('0 6 1 1 *'), timedelta(days=365))

    def test_cron_semanal_por_dia_da_semana(self):
        self.assertEqual(_intervalo_estimado('0 6 * * 1'), timedelta(days=7))

    def test_cron_diario_continua_diario(self):
        self.assertEqual(_intervalo_estimado('0 6 * * *'), timedelta(days=1))

    def test_cron_horario_continua_horario(self):
        self.assertEqual(_intervalo_estimado('0 * * * *'), timedelta(hours=1))

    def test_cron_a_cada_n_minutos(self):
        self.assertEqual(_intervalo_estimado('*/10 * * * *'), timedelta(minutes=10))

    def test_cron_invalido_devolve_none(self):
        """None = 'não sei julgar', que é diferente de 'está em dia'."""
        self.assertIsNone(_intervalo_estimado('nao é cron'))
        self.assertIsNone(_intervalo_estimado(None))
