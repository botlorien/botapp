"""Testes da integração de CI contra um servidor FALSO.

Nenhum host, token, grupo ou projeto real aparece aqui — o pacote é público, e
fixture com dado de cliente é vazamento. O duplo de teste responde no localhost.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from django.test import TestCase, override_settings

from botapp.ci_client import (CIConfigError, CIError, GitLabClient, fingerprint,
                              resolve_token)
from botapp.models import Alert, Bot, CIConnection, CIJob, CIPipeline, CIProject

TOKEN_FALSO = 'token-de-teste-nao-real'


class ServidorFalso(BaseHTTPRequestHandler):
    """Responde o mínimo da API que o cliente usa, com paginação de verdade."""

    rotas = {}
    recebidos = []

    def do_GET(self):  # noqa: N802 - assinatura da stdlib
        ServidorFalso.recebidos.append({
            'path': self.path,
            'token': self.headers.get('PRIVATE-TOKEN'),
        })
        # casa o prefixo MAIS LONGO: com casamento por ordem, a rota
        # ".../pipelines/900" capturaria ".../pipelines/900/jobs" e o teste
        # falharia por um motivo que não é o do produto
        candidatos = sorted((p for p in ServidorFalso.rotas
                             if self.path.startswith(p)), key=len, reverse=True)
        for prefixo in candidatos:
            resposta = ServidorFalso.rotas[prefixo]
            if True:
                corpo, cabecalhos = resposta(self.path) if callable(resposta) else resposta
                dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                for k, v in cabecalhos.items():
                    self.send_header(k, v)
                self.send_header('Content-Length', str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)
                return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *args):  # silencia o log do servidor de teste
        pass


class BaseCI(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ServidorFalso.rotas = {}
        cls.servidor = HTTPServer(('127.0.0.1', 0), ServidorFalso)
        cls.porta = cls.servidor.server_address[1]
        cls.thread = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f'http://127.0.0.1:{cls.porta}'

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        super().tearDownClass()

    def setUp(self):
        ServidorFalso.recebidos = []
        os.environ['BOTAPP_CI_ALLOW_INSECURE'] = 'true'   # localhost sem TLS
        os.environ['BOTAPP_CI_TOKEN'] = TOKEN_FALSO
        from botapp import ci_client
        self.ci_client = ci_client   # sem reload: flags são lidas por chamada

    def conexao(self, **extra):
        campos = dict(name='teste', base_url=self.base_url, namespace='grupo-x',
                      token_source='env', token_env_var='BOTAPP_CI_TOKEN')
        campos.update(extra)
        return CIConnection.objects.create(**campos)

    def cliente(self):
        return self.ci_client.GitLabClient(self.base_url, TOKEN_FALSO)


class TestToken(BaseCI):
    def test_resolve_token_do_ambiente(self):
        self.assertEqual(resolve_token(self.conexao()), TOKEN_FALSO)

    def test_env_ausente_da_erro_claro(self):
        conexao = self.conexao(token_env_var='BOTAPP_CI_TOKEN_INEXISTENTE')
        with self.assertRaises(CIConfigError) as ctx:
            resolve_token(conexao)
        self.assertIn('BOTAPP_CI_TOKEN_INEXISTENTE', str(ctx.exception))

    def test_modo_db_sem_chave_e_recusado(self):
        """Sem BOTAPP_CI_TOKEN_KEY o token NÃO pode ser aceito — melhor falhar
        do que guardar credencial em texto puro."""
        conexao = self.conexao(token_source='db')
        os.environ.pop('BOTAPP_CI_TOKEN_KEY', None)
        with self.assertRaises(CIConfigError) as ctx:
            resolve_token(conexao)
        self.assertIn('BOTAPP_CI_TOKEN_KEY', str(ctx.exception))

    def test_fingerprint_nao_revela_o_token(self):
        fp = fingerprint(TOKEN_FALSO)
        self.assertEqual(len(fp), 12)
        self.assertNotIn(fp, TOKEN_FALSO)
        self.assertNotIn(TOKEN_FALSO, fp)


class TestClienteHttp(BaseCI):
    def test_https_obrigatorio_por_default(self):
        os.environ['BOTAPP_CI_ALLOW_INSECURE'] = 'false'
        with self.assertRaises(CIConfigError):
            GitLabClient('http://exemplo.invalido', TOKEN_FALSO)

    def test_paginacao_usa_header_e_nao_o_tamanho_do_lote(self):
        """Contar itens do lote falha quando o total é múltiplo de per_page —
        o header X-Next-Page é a fonte da verdade."""
        pagina1 = [{'id': i, 'path_with_namespace': f'g/p{i}'} for i in range(100)]
        pagina2 = [{'id': 100, 'path_with_namespace': 'g/p100'}]

        def responder(path):
            if 'page=2' in path:
                return pagina2, {}
            return pagina1, {'X-Next-Page': '2'}

        ServidorFalso.rotas = {'/api/v4/groups/': responder}
        itens = list(self.cliente().projetos('grupo-x'))
        self.assertEqual(len(itens), 101)

    def test_per_page_e_fixado_no_maximo(self):
        ServidorFalso.rotas = {'/api/v4/groups/': ([], {})}
        list(self.cliente().projetos('grupo-x'))
        self.assertIn('per_page=100', ServidorFalso.recebidos[0]['path'])

    def test_rota_ausente_vira_CIError(self):
        ServidorFalso.rotas = {}
        with self.assertRaises(CIError):
            self.cliente().testar_conexao()

    def test_token_vai_no_header_e_nao_na_url(self):
        ServidorFalso.rotas = {'/api/v4/version': ({'version': '1.0'}, {})}
        self.cliente().testar_conexao()
        recebido = ServidorFalso.recebidos[0]
        self.assertEqual(recebido['token'], TOKEN_FALSO)
        self.assertNotIn(TOKEN_FALSO, recebido['path'])

    def test_trace_trunca_mantendo_o_final(self):
        """Quando trunca, o FIM é o que importa: é onde está o traceback."""
        corpo = ('linha de enchimento\n' * 5000 + 'ULTIMA LINHA IMPORTANTE\n').encode()
        ServidorFalso.rotas = {'/api/v4/projects/1/jobs/2/trace': (corpo, {})}
        texto, truncado = self.cliente().trace(1, 2, max_bytes=200)
        self.assertTrue(truncado)
        self.assertIn('ULTIMA LINHA IMPORTANTE', texto)
        self.assertLessEqual(len(texto.encode()), 200)


class TestSync(BaseCI):
    def _rotas_completas(self, status_pipeline='success', log=b'tudo certo\n'):
        return {
            '/api/v4/groups/': ([{'id': 7, 'path_with_namespace': 'g/proj',
                                  'name': 'proj', 'web_url': 'http://x/g/proj',
                                  'default_branch': 'main', 'archived': False}], {}),
            '/api/v4/projects/7/pipeline_schedules': (
                [{'id': 33, 'description': 'diario', 'cron': '0 5 * * *',
                  'cron_timezone': 'UTC', 'active': True,
                  'next_run_at': '2030-01-01T05:00:00Z'}], {}),
            '/api/v4/projects/7/pipelines/900': (
                {'id': 900, 'iid': 9, 'status': status_pipeline, 'source': 'schedule',
                 'ref': 'main', 'sha': 'abc', 'web_url': 'http://x/p/900',
                 'created_at': '2026-01-01T10:00:00Z',
                 'started_at': '2026-01-01T10:00:05Z',
                 'finished_at': '2026-01-01T10:01:00Z', 'duration': 55,
                 'user': {'username': 'operador'}}, {}),
            '/api/v4/projects/7/pipelines/900/jobs': (
                [{'id': 5001, 'name': 'executa', 'stage': 'run',
                  'status': status_pipeline, 'duration': 50,
                  'runner': {'description': 'runner-de-teste'}}], {}),
            '/api/v4/projects/7/pipelines': (
                [{'id': 900, 'status': status_pipeline}], {}),
            '/api/v4/projects/7/jobs/5001/trace': (log, {}),
        }

    def test_descoberta_cria_projeto_e_agendamento(self):
        ServidorFalso.rotas = self._rotas_completas()
        from botapp.ci_sync import sync_projects
        conexao = self.conexao()
        resultado = sync_projects(conexao, self.cliente())
        self.assertEqual(resultado['projetos_criados'], 1)
        projeto = CIProject.objects.get(external_id=7)
        self.assertEqual(projeto.path, 'g/proj')
        self.assertEqual(projeto.schedules.count(), 1)
        self.assertEqual(projeto.schedules.first().cron, '0 5 * * *')

    def test_pipeline_falho_gera_alerta_e_guarda_cauda(self):
        ServidorFalso.rotas = self._rotas_completas(
            status_pipeline='failed', log=b'passo 1\nTraceback (most recent call last)\nboom\n')
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        resultado = sync_pipelines(conexao, self.cliente())
        self.assertEqual(resultado['pipelines_novos'], 1)
        self.assertEqual(
            Alert.objects.filter(type=Alert.Type.PIPELINE_FAILED).count(), 1)
        job = CIJob.objects.get(external_id=5001)
        self.assertIn('boom', job.log_excerpt)

    def test_verde_com_traceback_gera_alerta_de_mascaramento(self):
        """O caso mais difícil de achar: CI diz sucesso e a exceção foi engolida."""
        ServidorFalso.rotas = self._rotas_completas(
            status_pipeline='success',
            log=b'INFO ok\nTraceback (most recent call last)\nOperationalError\n')
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        CIProject.objects.filter(external_id=7).update(scan_logs=True)
        sync_pipelines(conexao, self.cliente())
        self.assertEqual(
            Alert.objects.filter(type=Alert.Type.PIPELINE_MASKED_ERROR).count(), 1)
        self.assertTrue(CIPipeline.objects.get(external_id=900).has_masked_error)

    def test_ignore_patterns_evitam_falso_positivo(self):
        ServidorFalso.rotas = self._rotas_completas(
            status_pipeline='success', log=b'CRITICAL ruido conhecido\n')
        os.environ['BOTAPP_CI_IGNORE_PATTERNS'] = 'ruido conhecido'
        try:
            from botapp.ci_sync import sync_pipelines, sync_projects
            conexao = self.conexao()
            sync_projects(conexao, self.cliente())
            CIProject.objects.filter(external_id=7).update(scan_logs=True)
            sync_pipelines(conexao, self.cliente())
            self.assertEqual(
                Alert.objects.filter(
                    type=Alert.Type.PIPELINE_MASKED_ERROR).count(), 0)
        finally:
            os.environ.pop('BOTAPP_CI_IGNORE_PATTERNS', None)

    def test_scan_logs_desligado_nao_busca_log(self):
        ServidorFalso.rotas = self._rotas_completas(
            status_pipeline='success', log=b'Traceback (most recent call last)\n')
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        sync_pipelines(conexao, self.cliente())   # scan_logs default = False
        self.assertEqual(
            Alert.objects.filter(type=Alert.Type.PIPELINE_MASKED_ERROR).count(), 0)
        self.assertFalse(
            any('/trace' in r['path'] for r in ServidorFalso.recebidos))

    def test_triggered_by_pode_ser_desligado(self):
        ServidorFalso.rotas = self._rotas_completas()
        os.environ['BOTAPP_CI_STORE_TRIGGERED_BY'] = 'false'
        try:
            from botapp.ci_sync import sync_pipelines, sync_projects
            conexao = self.conexao()
            sync_projects(conexao, self.cliente())
            sync_pipelines(conexao, self.cliente())
            self.assertEqual(CIPipeline.objects.get(external_id=900).triggered_by, '')
        finally:
            os.environ.pop('BOTAPP_CI_STORE_TRIGGERED_BY', None)

    def test_triggered_by_ligado_por_default(self):
        ServidorFalso.rotas = self._rotas_completas()
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        sync_pipelines(conexao, self.cliente())
        self.assertEqual(CIPipeline.objects.get(external_id=900).triggered_by,
                         'operador')

    def test_alerta_nao_repete_a_cada_ciclo(self):
        ServidorFalso.rotas = self._rotas_completas(status_pipeline='failed')
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        sync_pipelines(conexao, self.cliente())
        CIProject.objects.filter(external_id=7).update(pipelines_cursor=None)
        CIPipeline.objects.all().delete()          # força reprocessar
        sync_pipelines(conexao, self.cliente())
        self.assertEqual(
            Alert.objects.filter(type=Alert.Type.PIPELINE_FAILED).count(), 1)

    def test_falha_de_um_projeto_nao_derruba_o_ciclo(self):
        """Isolamento por projeto: 403/timeout de um não pode parar os outros."""
        ServidorFalso.rotas = {
            '/api/v4/groups/': ([
                {'id': 7, 'path_with_namespace': 'g/bom'},
                {'id': 8, 'path_with_namespace': 'g/ruim'},
            ], {}),
            '/api/v4/projects/7/pipeline_schedules': ([], {}),
            '/api/v4/projects/8/pipeline_schedules': ([], {}),
            '/api/v4/projects/7/pipelines': ([], {}),
            # projeto 8 sem rota de pipelines => 404 => erro isolado
        }
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        resultado = sync_pipelines(conexao, self.cliente())
        self.assertEqual(resultado['projetos'], 2)
        ruim = CIProject.objects.get(external_id=8)
        self.assertTrue(ruim.last_sync_error)
        bom = CIProject.objects.get(external_id=7)
        self.assertFalse(bom.last_sync_error)


class TestAgendamentoSemExecucao(BaseCI):
    def test_agendamento_ativo_sem_pipeline_alerta(self):
        """A armadilha real: o agendamento existe, está ativo e não dispara."""
        from botapp.ci_sync import avaliar_agendamentos
        conexao = self.conexao()
        projeto = CIProject.objects.create(
            connection=conexao, external_id=7, path='g/proj', name='proj')
        projeto.schedules.create(external_id=1, cron='0 * * * *', active=True)
        alertas = avaliar_agendamentos(conexao)
        self.assertEqual(alertas, 1)
        self.assertTrue(
            Alert.objects.filter(type=Alert.Type.PROJECT_NEVER_RAN).exists())


class TestProgressoECusto(BaseCI):
    def test_primeiro_ciclo_puxa_menos_por_projeto(self):
        """Sem cursor, o limite é o reduzido — senão o primeiro ciclo leva horas."""
        muitos = [{'id': 900 + i, 'status': 'success'} for i in range(40)]
        rotas = self._rotas_base()
        rotas['/api/v4/projects/7/pipelines'] = (muitos, {})
        for i in range(40):
            rotas[f'/api/v4/projects/7/pipelines/{900 + i}'] = (
                {'id': 900 + i, 'status': 'success', 'source': 'push',
                 'created_at': '2026-01-01T10:00:00Z'}, {})
            rotas[f'/api/v4/projects/7/pipelines/{900 + i}/jobs'] = ([], {})
        ServidorFalso.rotas = rotas

        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        r = sync_pipelines(conexao, self.cliente(), limite_por_projeto=50,
                           limite_primeira_vez=5)
        self.assertEqual(r['pipelines_novos'], 5)

    def test_progresso_aparece_antes_do_fim_do_ciclo(self):
        """O painel não pode dizer 'nunca sincronizado' enquanto o sync trabalha."""
        ServidorFalso.rotas = self._rotas_base()
        from botapp.ci_sync import sync_projects
        conexao = self.conexao()
        self.assertEqual(conexao.last_sync_status, 'never')
        sync_projects(conexao, self.cliente())
        conexao.refresh_from_db()
        self.assertEqual(conexao.last_sync_status, 'ok')
        self.assertIsNotNone(conexao.last_sync_at)

    def _rotas_base(self):
        return {
            '/api/v4/groups/': ([{'id': 7, 'path_with_namespace': 'g/proj',
                                  'name': 'proj'}], {}),
            '/api/v4/projects/7/pipeline_schedules': ([], {}),
            '/api/v4/projects/7/pipelines': ([], {}),
        }


class TestLimpezaAnsi(BaseCI):
    def test_ansi_nao_esconde_padrao_nem_vaza_para_o_excerpt(self):
        """Código de cor no meio da linha não pode fazer o padrão passar batido."""
        from botapp.ci_sync import limpar_ansi, sync_pipelines, sync_projects
        sujo = '\x1b[31;1mTraceback (most recent call last)\x1b[0;m\nboom\n'
        self.assertIn('Traceback (most recent call last)', limpar_ansi(sujo))
        self.assertNotIn('\x1b[', limpar_ansi(sujo))

        ServidorFalso.rotas = self._rotas_completas(
            status_pipeline='success', log=sujo.encode())
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        CIProject.objects.filter(external_id=7).update(scan_logs=True)
        sync_pipelines(conexao, self.cliente())
        self.assertEqual(
            Alert.objects.filter(type=Alert.Type.PIPELINE_MASKED_ERROR).count(), 1)
        job = CIJob.objects.get(external_id=5001)
        self.assertNotIn('\x1b[', job.log_excerpt)

    def _rotas_completas(self, status_pipeline='success', log=b''):
        return TestSync._rotas_completas(self, status_pipeline, log)


class TestAlertaObsoleto(BaseCI):
    def test_alerta_de_falha_some_quando_o_run_seguinte_passa(self):
        """Alerta velho poluindo o painel esconde o alerta que importa."""
        from botapp.ci_sync import resolver_alertas_obsoletos
        from django.utils import timezone
        from datetime import timedelta

        conexao = self.conexao()
        projeto = CIProject.objects.create(connection=conexao, external_id=7,
                                           path='g/proj', name='proj')
        agora = timezone.now()
        ruim = CIPipeline.objects.create(project=projeto, external_id=100,
                                         status='failed',
                                         created_at=agora - timedelta(hours=2))
        Alert.objects.create(type=Alert.Type.PIPELINE_FAILED,
                             severity=Alert.Severity.HIGH,
                             message='falhou',
                             payload={'project_id': projeto.id,
                                      'pipeline_id': ruim.external_id})
        # ainda não há run posterior: o alerta PERMANECE
        self.assertEqual(resolver_alertas_obsoletos(conexao), 0)

        CIPipeline.objects.create(project=projeto, external_id=101,
                                  status='success',
                                  created_at=agora - timedelta(minutes=10))
        self.assertEqual(resolver_alertas_obsoletos(conexao), 1)
        self.assertIsNotNone(Alert.objects.first().resolved_at)

    def test_projeto_que_segue_falhando_mantem_o_alerta(self):
        from botapp.ci_sync import resolver_alertas_obsoletos
        from django.utils import timezone
        from datetime import timedelta

        conexao = self.conexao()
        projeto = CIProject.objects.create(connection=conexao, external_id=8,
                                           path='g/ruim', name='ruim')
        agora = timezone.now()
        ruim = CIPipeline.objects.create(project=projeto, external_id=200,
                                         status='failed',
                                         created_at=agora - timedelta(hours=2))
        CIPipeline.objects.create(project=projeto, external_id=201,
                                  status='failed',
                                  created_at=agora - timedelta(minutes=5))
        Alert.objects.create(type=Alert.Type.PIPELINE_FAILED,
                             severity=Alert.Severity.HIGH, message='falhou',
                             payload={'project_id': projeto.id,
                                      'pipeline_id': ruim.external_id})
        self.assertEqual(resolver_alertas_obsoletos(conexao), 0)

    def test_verde_com_erro_nao_conta_como_recuperacao(self):
        """Um 'sucesso' que tem erro no log não prova que voltou a funcionar."""
        from botapp.ci_sync import resolver_alertas_obsoletos
        from django.utils import timezone
        from datetime import timedelta

        conexao = self.conexao()
        projeto = CIProject.objects.create(connection=conexao, external_id=9,
                                           path='g/x', name='x')
        agora = timezone.now()
        ruim = CIPipeline.objects.create(project=projeto, external_id=300,
                                         status='failed',
                                         created_at=agora - timedelta(hours=2))
        CIPipeline.objects.create(project=projeto, external_id=301,
                                  status='success', has_masked_error=True,
                                  created_at=agora - timedelta(minutes=5))
        Alert.objects.create(type=Alert.Type.PIPELINE_FAILED,
                             severity=Alert.Severity.HIGH, message='falhou',
                             payload={'project_id': projeto.id,
                                      'pipeline_id': ruim.external_id})
        self.assertEqual(resolver_alertas_obsoletos(conexao), 0)


class TestPayloadDoAlerta(BaseCI):
    def test_alerta_carrega_ids_para_o_painel_linkar(self):
        ServidorFalso.rotas = TestSync._rotas_completas(self, 'failed')
        from botapp.ci_sync import sync_pipelines, sync_projects
        conexao = self.conexao()
        sync_projects(conexao, self.cliente())
        sync_pipelines(conexao, self.cliente())
        a = Alert.objects.get(type=Alert.Type.PIPELINE_FAILED)
        self.assertIn('pipeline_db_id', a.payload)
        self.assertIn('job_db_id', a.payload)
        self.assertTrue(CIPipeline.objects.filter(id=a.payload['pipeline_db_id']).exists())
        self.assertTrue(CIJob.objects.filter(id=a.payload['job_db_id']).exists())


class TestSemVazamento(TestCase):
    """O pacote é público: o código não pode citar organização nem credencial."""

    def test_nenhum_default_de_servidor_no_codigo(self):
        import inspect

        from botapp import ci_client, ci_sync
        for modulo in (ci_client, ci_sync):
            fonte = inspect.getsource(modulo)
            self.assertNotIn('https://gitlab.com', fonte,
                             f'{modulo.__name__} não pode ter servidor default')
            for proibido in ('glpat-', 'glrt-'):
                self.assertNotIn(proibido, fonte)
