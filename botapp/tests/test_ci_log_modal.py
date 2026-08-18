"""A modal de log tem de existir e funcionar igual em toda tela que lista
pipeline — bot, projeto e pipeline."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from botapp.models import Bot, CIConnection, CIJob, CIPipeline, CIProject


@override_settings(BOTAPP_CI_ENABLED=True)
class ModalDeLog(TestCase):
    def setUp(self):
        conexao = CIConnection.objects.create(
            name='c', base_url='https://exemplo.invalido', namespace='g',
            token_source='env', token_env_var='BOTAPP_CI_TOKEN')
        self.bot = Bot.objects.create(name='bot x', description='d', version='1')
        self.projeto = CIProject.objects.create(
            connection=conexao, external_id=1, path='g/bot_x', name='bot_x',
            bot=self.bot)
        self.pipeline = CIPipeline.objects.create(
            project=self.projeto, external_id=77, status='failed')
        self.job = CIJob.objects.create(pipeline=self.pipeline, external_id=5,
                                        name='deploy', status='failed')
        usuario = get_user_model().objects.create_user(
            'adm', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)

    def _html(self, url):
        return self.client.get(url).content.decode()

    def test_modal_presente_nas_tres_telas(self):
        for url in (f'/bots/{self.bot.id}/',
                    f'/ci/projects/{self.projeto.id}/',
                    f'/ci/pipelines/{self.pipeline.id}/'):
            html = self._html(url)
            self.assertIn('id="modal-log-ci"', html, url)
            self.assertIn('function abrirLogsPipeline', html, url)

    def test_uma_definicao_por_pagina(self):
        """A modal virou include; se alguma tela mantiver a cópia antiga, as
        funções ficam definidas duas vezes e a última silenciosamente vence."""
        for url in (f'/bots/{self.bot.id}/',
                    f'/ci/pipelines/{self.pipeline.id}/'):
            html = self._html(url)
            self.assertEqual(html.count('function abrirLogsPipeline'), 1, url)
            self.assertEqual(html.count('id="modal-log-ci"'), 1, url)

    def test_tela_da_pipeline_abre_o_job_da_linha(self):
        html = self._html(f'/ci/pipelines/{self.pipeline.id}/')
        self.assertIn(f'data-job="{self.job.id}"', html)
        self.assertIn(f'data-pipeline="{self.pipeline.id}"', html)

    def test_endpoint_de_jobs_alimenta_a_modal(self):
        r = self.client.get(f'/ci/pipelines/{self.pipeline.id}/jobs.json',
                            headers={'X-Requested-With': 'XMLHttpRequest'})
        dados = r.json()
        self.assertTrue(dados['ok'])
        self.assertEqual([j['nome'] for j in dados['jobs']], ['deploy'])

    def test_log_sai_como_texto(self):
        """Conteúdo do CI não pode ser servido como HTML."""
        r = self.client.get(f'/ci/jobs/{self.job.id}/excerpt/')
        self.assertIn('text/plain', r['Content-Type'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
