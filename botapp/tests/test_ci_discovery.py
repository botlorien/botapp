"""Descoberta sob demanda e a mensagem de tela vazia."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from botapp.models import CIConnection, CIProject


@override_settings(BOTAPP_CI_ENABLED=True)
class DescobertaSobDemanda(TestCase):
    def setUp(self):
        self.conexao = CIConnection.objects.create(
            name='c', base_url='https://exemplo.invalido', namespace='g',
            token_source='env', token_env_var='BOTAPP_CI_TOKEN',
            discovery_interval_minutes=1440)
        usuario = get_user_model().objects.create_user(
            'adm', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)

    def test_botao_aparece_para_quem_pode_editar(self):
        html = self.client.get('/ci/projects/').content.decode()
        self.assertIn('/ci/discover/', html)
        self.assertIn('Sincronizar agora', html)

    def test_anonimo_nao_dispara_descoberta(self):
        from django.test import Client
        r = Client().post('/ci/discover/')
        self.assertIn(r.status_code, (302, 403))

    def test_get_nao_dispara_descoberta(self):
        """Efeito colateral não pode acontecer por navegação."""
        self.assertEqual(self.client.get('/ci/discover/').status_code, 405)

    def test_mensagem_distingue_filtro_de_banco_vazio(self):
        """Sem nada no banco, orienta a sincronizar. Com projeto no banco mas
        filtro sem resultado, dizer 'nada sincronizado' induzia a rodar um
        comando desnecessário."""
        html = self.client.get('/ci/projects/').content.decode()
        self.assertIn('Nenhum projeto sincronizado ainda', html)

        CIProject.objects.create(connection=self.conexao, external_id=1,
                                 path='g/algum', name='algum')
        html = self.client.get('/ci/projects/?q=inexistente').content.decode()
        self.assertIn('Nenhum projeto corresponde a este filtro', html)
        self.assertNotIn('Nenhum projeto sincronizado ainda', html)

    def test_passada_rapida_nao_reinicia_o_relogio_da_completa(self):
        """A rápida pula os agendamentos; se marcasse last_discovery_at, eles
        ficariam sem sincronizar por mais um intervalo inteiro."""
        from unittest.mock import patch

        from botapp.ci_sync import sync_projects
        antes = timezone.now() - timedelta(days=3)
        CIConnection.objects.filter(pk=self.conexao.pk).update(
            last_discovery_at=antes)
        self.conexao.refresh_from_db()

        with patch('botapp.ci_sync.client_for') as fake:
            fake.return_value.projetos.return_value = [
                {'id': 7, 'path_with_namespace': 'g/novo', 'name': 'novo',
                 'web_url': '', 'default_branch': 'main', 'archived': False}]
            r = sync_projects(self.conexao, com_agendamentos=False)

        self.conexao.refresh_from_db()
        self.assertEqual(r['projetos_criados'], 1)
        self.assertTrue(CIProject.objects.filter(path='g/novo').exists())
        self.assertEqual(self.conexao.last_discovery_at, antes)

    def test_passada_completa_reinicia_o_relogio(self):
        from unittest.mock import patch

        from botapp.ci_sync import sync_projects
        CIConnection.objects.filter(pk=self.conexao.pk).update(
            last_discovery_at=timezone.now() - timedelta(days=3))

        with patch('botapp.ci_sync.client_for') as fake:
            fake.return_value.projetos.return_value = [
                {'id': 8, 'path_with_namespace': 'g/outro', 'name': 'outro',
                 'web_url': '', 'default_branch': 'main', 'archived': False}]
            fake.return_value.agendamentos.return_value = []
            sync_projects(self.conexao, com_agendamentos=True)

        self.conexao.refresh_from_db()
        self.assertLess(timezone.now() - self.conexao.last_discovery_at,
                        timedelta(minutes=1))
