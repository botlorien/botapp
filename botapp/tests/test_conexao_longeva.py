"""Conexão de banco em processo que vive dias.

Caso real (10/09/2026): o servidor de banco reiniciou. Todo processo longevo com
conexão aberta passou a falhar em TODA operação seguinte com
`InterfaceError: connection already closed` — o driver não é avisado do
fechamento, só descobre ao usar o socket.

Três consumidores do pacote sofrem disso, com gravidades diferentes:

* o **laço de sincronização de CI** capturava a exceção, logava "segue para o
  próximo" e tentava de novo com a MESMA conexão morta. Ficou 14h sem
  sincronizar, com o processo vivo e o último status gravado como `ok` — ou
  seja, o painel ficou cego sem nada indicar isso;
* o **laço de alertas** tem o mesmo desenho;
* o **SDK** (`@app.task`) falhava já no registro da task, antes de criar o
  TaskLog. Num bot de execução única isso é uma execução perdida; num bot que
  roda em laço, são todas as seguintes.

A correção não é capturar melhor: é **renovar a conexão**. Usamos a detecção do
próprio Django (`close_if_unusable_or_obsolete`, onde `is_usable()` descobre o
socket morto), mas pulando conexão com transação aberta — fechar ali descartaria
o trabalho do chamador. A conexão seguinte nasce nova.

Há ainda o caso em que a conexão morre DURANTE o trabalho: aí a gravação do fim
do TaskLog falharia e a execução ficaria eternamente em `started`, que é o
padrão que gera alerta de execução órfã. Por isso a gravação final tem uma
segunda tentativa após renovar.
"""
from unittest import mock

from django.db.utils import InterfaceError, OperationalError
from django.test import SimpleTestCase, TestCase

from botapp import dbconn
from botapp.models import Bot, Task, TaskLog


class ConexaoFalsa:
    def __init__(self, alias='default', em_transacao=False):
        self.alias = alias
        self.in_atomic_block = em_transacao
        self.renovada = False

    def close_if_unusable_or_obsolete(self):
        self.renovada = True


class RenovarConexoes(SimpleTestCase):
    def test_usa_a_deteccao_do_django(self):
        """Não reinventamos a detecção: `is_usable()` do Django já a faz."""
        conexao = ConexaoFalsa()
        with mock.patch.object(dbconn.connections, 'all', return_value=[conexao]):
            dbconn.renovar_conexoes()
        self.assertTrue(conexao.renovada)

    def test_conexao_em_transacao_nao_e_fechada(self):
        """Fechar dentro de `atomic()` descartaria a transação do chamador.

        É a razão de não usar `close_old_connections()` direto: ele fecha quando
        o autocommit está desligado, que é justamente o estado de quem está numa
        transação.
        """
        aberta = ConexaoFalsa('default', em_transacao=True)
        livre = ConexaoFalsa('replica', em_transacao=False)
        with mock.patch.object(dbconn.connections, 'all',
                               return_value=[aberta, livre]):
            dbconn.renovar_conexoes()
        self.assertFalse(aberta.renovada, 'transação em curso foi descartada')
        self.assertTrue(livre.renovada)

    def test_falha_ao_renovar_nao_propaga(self):
        """Renovar é preventivo; explodir aqui derrubaria o trabalho útil."""
        with mock.patch.object(dbconn.connections, 'all',
                               side_effect=OSError('socket já fechado')):
            dbconn.renovar_conexoes()      # não pode levantar


class ExecutarReconectando(SimpleTestCase):
    def test_sucesso_direto_nao_renova_nada(self):
        with mock.patch.object(dbconn, 'renovar_conexoes') as renovar:
            self.assertEqual(dbconn.executar_reconectando(lambda: 42), 42)
        renovar.assert_not_called()

    def test_conexao_morta_renova_e_tenta_de_novo(self):
        """O caso do servidor reiniciado: a 2ª tentativa pega conexão nova."""
        tentativas = []

        def instavel():
            tentativas.append(1)
            if len(tentativas) == 1:
                raise InterfaceError('connection already closed')
            return 'ok'

        with mock.patch.object(dbconn, 'renovar_conexoes') as renovar:
            self.assertEqual(dbconn.executar_reconectando(instavel), 'ok')
        self.assertEqual(len(tentativas), 2)
        renovar.assert_called_once_with()

    def test_operational_error_tambem_conta_como_conexao(self):
        """`server closed the connection unexpectedly` chega como OperationalError."""
        tentativas = []

        def instavel():
            tentativas.append(1)
            if len(tentativas) == 1:
                raise OperationalError('server closed the connection unexpectedly')
            return 'ok'

        with mock.patch.object(dbconn, 'renovar_conexoes'):
            self.assertEqual(dbconn.executar_reconectando(instavel), 'ok')
        self.assertEqual(len(tentativas), 2)

    def test_erro_que_nao_e_de_conexao_nao_repete(self):
        """Repetir erro de programação esconderia o defeito e dobraria efeito."""
        tentativas = []

        def quebrado():
            tentativas.append(1)
            raise ValueError('coluna inexistente')

        with self.assertRaises(ValueError):
            dbconn.executar_reconectando(quebrado)
        self.assertEqual(len(tentativas), 1)

    def test_esgotadas_as_tentativas_o_erro_sobe(self):
        """Banco fora do ar de verdade não pode virar silêncio."""
        def sempre_morta():
            raise InterfaceError('connection already closed')

        with mock.patch.object(dbconn, 'renovar_conexoes'):
            with self.assertRaises(InterfaceError):
                dbconn.executar_reconectando(sempre_morta, tentativas=3)

    def test_argumentos_sao_repassados(self):
        self.assertEqual(
            dbconn.executar_reconectando(lambda a, b=0: a + b, 2, b=3), 5)


class SdkRenovaAntesDeUsarOBanco(TestCase):
    """O ponto exato onde o bot longevo quebrou: registro da task."""

    def setUp(self):
        self.bot = Bot.objects.create(name='bot-de-teste', version='1.0.0')

    def test_wrapper_renova_a_conexao_antes_de_tocar_no_banco(self):
        from botapp.core import BotApp

        app = BotApp.__new__(BotApp)
        app.bot_instance = self.bot

        # patch no módulo que USA: `decorators` importou a referência, então
        # trocar em `dbconn` não afetaria a chamada
        from botapp import decorators
        with mock.patch.object(decorators, 'renovar_conexoes') as renovar:
            @app.task
            def tarefa():
                """faz algo"""
                return 'pronto'

            tarefa()

        self.assertTrue(renovar.called, 'a conexão precisa ser renovada por execução')

    def test_fim_da_execucao_e_gravado_mesmo_com_conexao_caindo_no_meio(self):
        """Sem isto a execução fica `started` para sempre e vira alerta órfão."""
        from botapp.core import BotApp

        app = BotApp.__new__(BotApp)
        app.bot_instance = self.bot
        tarefa_obj = Task.objects.create(bot=self.bot, name='demorada')
        log = TaskLog.objects.create(task=tarefa_obj, status=TaskLog.Status.STARTED)

        chamadas = []
        original = TaskLog.save

        def save_instavel(self, *a, **kw):
            chamadas.append(1)
            if len(chamadas) == 1:
                raise InterfaceError('connection already closed')
            return original(self, *a, **kw)

        with mock.patch.object(TaskLog, 'save', save_instavel):
            with mock.patch.object(dbconn, 'renovar_conexoes'):
                log.status = TaskLog.Status.COMPLETED
                dbconn.executar_reconectando(log.save)

        log.refresh_from_db()
        self.assertEqual(log.status, TaskLog.Status.COMPLETED)
        self.assertEqual(len(chamadas), 2, 'devia ter tentado de novo após renovar')


class LacosRenovamACadaCiclo(SimpleTestCase):
    """Os dois laços que rodam ao lado do servidor web.

    O de CI foi o que ficou 14h girando em falso: capturava a exceção, logava
    "segue para o próximo" e repetia com a mesma conexão morta, com o processo
    vivo e o último status gravado como `ok`.
    """

    def test_laco_de_ci_renova_antes_de_cada_ciclo(self):
        from botapp.management.commands import run_ci_scheduler

        ordem = []
        comando = run_ci_scheduler.Command()
        with mock.patch.object(run_ci_scheduler, 'renovar_conexoes',
                               side_effect=lambda: ordem.append('renovou')), \
                mock.patch.object(run_ci_scheduler, 'call_command',
                                  side_effect=lambda *a, **k: ordem.append('sincronizou')):
            comando.handle(interval=60, once=True)

        self.assertEqual(ordem, ['renovou', 'sincronizou'],
                         'renovar tem de vir ANTES de usar o banco')

    def test_laco_de_ci_renova_mesmo_depois_de_ciclo_que_falhou(self):
        """O ciclo seguinte ao erro é justamente o que precisa de conexão nova."""
        from botapp.management.commands import run_ci_scheduler

        ordem = []
        ciclos = []

        def sync_instavel(*a, **k):
            ciclos.append(1)
            ordem.append('sincronizou')
            if len(ciclos) == 1:
                raise InterfaceError('connection already closed')

        comando = run_ci_scheduler.Command()
        comando._parar = False

        def parar_no_segundo():
            ordem.append('renovou')
            if len(ciclos) >= 1:
                comando._parar = True

        with mock.patch.object(run_ci_scheduler, 'renovar_conexoes',
                               side_effect=parar_no_segundo), \
                mock.patch.object(run_ci_scheduler, 'call_command',
                                  side_effect=sync_instavel), \
                mock.patch.object(run_ci_scheduler.time, 'sleep'):
            comando.handle(interval=60, once=False)

        self.assertEqual(ordem[:2], ['renovou', 'sincronizou'])
        self.assertIn('renovou', ordem[2:], 'o ciclo após a falha não renovou')

    def test_laco_de_alertas_renova_antes_de_cada_ciclo(self):
        from botapp.management.commands import run_alert_scheduler

        ordem = []
        comando = run_alert_scheduler.Command()
        with mock.patch.object(run_alert_scheduler, 'renovar_conexoes',
                               side_effect=lambda: ordem.append('renovou')), \
                mock.patch.object(run_alert_scheduler, 'call_command',
                                  side_effect=lambda *a, **k: ordem.append('checou')):
            comando.handle(interval=60, once=True)

        self.assertEqual(ordem, ['renovou', 'checou'])
