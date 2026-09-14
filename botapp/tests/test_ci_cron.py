"""Estimativa de intervalo do cron — o que decide o limiar de schedule_without_run.

Caso real (05/09/2026): um projeto com agendamento MENSAL (`0 6 15 * *`,
dia 15 às 06:00) rodou normalmente no dia 15 do mês anterior. O estimador não
reconhecia dia-do-mês fixo e caía no fallback semanal, então o limiar virou
7d × 3 = 21d — e o alerta abriu com "504h sem execução" sobre um bot que
estava em dia e cuja próxima execução era o dia 15 seguinte.

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

    def test_horas_agrupadas_em_janela_medem_o_maior_intervalo(self):
        """`0 9,11,13,15,17 * * *` roda de 2 em 2h... das 9h às 17h.

        O buraco que importa é o NOTURNO: das 17h de um dia às 9h do outro são
        16h sem execução, e é exatamente esse o intervalo que o limiar precisa
        tolerar. Dividir 24h pelo número de horários (24//5 = 4h) supõe que os
        horários estão espalhados pelo dia inteiro — falso para a janela
        comercial, que é como quase todo bot da casa é agendado. Com 4h × 3 o
        alerta abria toda manhã sobre um bot que tinha rodado às 17h do dia
        anterior (alerta #1064, 14/09/2026).
        """
        self.assertEqual(_intervalo_estimado('0 9,11,13,15,17 * * *'),
                         timedelta(hours=16))

    def test_horas_espalhadas_continuam_pelo_maior_vao(self):
        """`0 8,20 * * *` = 12h de vão nos dois sentidos."""
        self.assertEqual(_intervalo_estimado('0 8,20 * * *'), timedelta(hours=12))

    def test_intervalo_de_horas_com_passo(self):
        """`0 9-17/2 * * *` é a mesma coisa que 9,11,13,15,17."""
        self.assertEqual(_intervalo_estimado('0 9-17/2 * * *'),
                         timedelta(hours=16))

    def test_dias_uteis_medem_o_fim_de_semana(self):
        """`0 10 * * 1-5` = de sexta a segunda são 3 dias, não 7.

        7 dias era o fallback de "tem algo no campo semana": erra para mais,
        mas cega o silent_bot, que passa a tolerar uma semana inteira de
        silêncio num bot que deveria rodar todo dia útil.
        """
        self.assertEqual(_intervalo_estimado('0 10 * * 1-5'), timedelta(days=3))

    def test_um_dia_da_semana_continua_semanal(self):
        self.assertEqual(_intervalo_estimado('0 6 * * 1'), timedelta(days=7))

    def test_dois_dias_da_semana_medem_o_maior_vao(self):
        """Segunda e quinta: 3 dias de um lado, 4 do outro."""
        self.assertEqual(_intervalo_estimado('0 6 * * 1,4'), timedelta(days=4))

    def test_domingo_como_0_e_como_7_sao_o_mesmo_dia(self):
        """cron aceita os dois; contar 0 e 7 como dias distintos inventa vão."""
        self.assertEqual(_intervalo_estimado('0 6 * * 0,7'), timedelta(days=7))

    def test_campo_de_hora_ilegivel_nao_derruba_a_estimativa(self):
        """Erra para MAIS: sem conseguir ler, o dia inteiro é o palpite seguro."""
        self.assertEqual(_intervalo_estimado('0 abc * * *'), timedelta(days=1))
