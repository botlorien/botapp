"""Vínculo bot × projeto de CI pelos dois lados da tela."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from botapp.models import Bot, CIConnection, CIProject


@override_settings(BOTAPP_CI_ENABLED=True)
class VinculoPelaTelaDoProjeto(TestCase):
    def setUp(self):
        self.conexao = CIConnection.objects.create(
            name='c', base_url='https://exemplo.invalido', namespace='g',
            token_source='env', token_env_var='BOTAPP_CI_TOKEN')
        self.projeto = CIProject.objects.create(
            connection=self.conexao, external_id=1,
            path='g/bot_exporta_relatorio_para_planilha',
            name='bot_exporta_relatorio_para_planilha')
        self.certo = Bot.objects.create(
            name='Bot exporta relatorio para planilha',
            description='x', version='1')
        self.outro = Bot.objects.create(name='Bot outro assunto',
                                        description='x', version='1')
        usuario = get_user_model().objects.create_user(
            'adm', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)
        self.url = f'/ci/projects/{self.projeto.id}/link-bot/'

    def test_tela_oferece_campo_pesquisavel_com_sugestao(self):
        html = self.client.get(f'/ci/projects/{self.projeto.id}/').content.decode()
        self.assertIn('name="bot_name"', html)
        self.assertIn(f'<datalist id="ci-bots-{self.projeto.id}">', html)
        # o bot de nome equivalente precisa vir marcado como sugestão
        self.assertIn(f'<option value="{self.certo.name}">sugerido</option>', html)

    def test_vincula_pelo_nome_digitado(self):
        self.client.post(self.url, {'bot_name': self.certo.name})
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.bot_id, self.certo.id)

    def test_nome_inexistente_avisa_e_nao_altera(self):
        self.projeto.bot = self.outro
        self.projeto.save()
        r = self.client.post(self.url, {'bot_name': 'não existe'}, follow=True)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.bot_id, self.outro.id)
        self.assertContains(r, 'Bot não encontrado')

    def test_nome_ambiguo_nao_escolhe_sozinho(self):
        """Nome de bot não é único; empate tem de virar aviso, não palpite."""
        Bot.objects.create(name=self.certo.name, description='y', version='2')
        r = self.client.post(self.url, {'bot_name': self.certo.name}, follow=True)
        self.projeto.refresh_from_db()
        self.assertIsNone(self.projeto.bot_id)
        self.assertContains(r, 'mais de um bot')

    def test_campo_vazio_nao_desvincula(self):
        """Salvar com o campo em branco não pode apagar um vínculo existente."""
        self.projeto.bot = self.certo
        self.projeto.save()
        self.client.post(self.url, {'bot_name': ''})
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.bot_id, self.certo.id)

    def test_desvincular_e_explicito(self):
        self.projeto.bot = self.certo
        self.projeto.save()
        self.client.post(self.url, {'desvincular': '1'})
        self.projeto.refresh_from_db()
        self.assertIsNone(self.projeto.bot_id)

    def test_bot_vinculado_e_clicavel(self):
        """O nome do bot na tela de CI leva à tela do bot."""
        self.projeto.bot = self.certo
        self.projeto.save()
        html = self.client.get(f'/ci/projects/{self.projeto.id}/').content.decode()
        self.assertIn(f'href="/bots/{self.certo.id}/"', html)

    def test_bot_ja_vinculado_sai_das_sugestoes(self):
        """Sugerir o bot que já está vinculado é oferecer ação sem efeito."""
        self.projeto.bot = self.certo
        self.projeto.save()
        r = self.client.get(f'/ci/projects/{self.projeto.id}/')
        self.assertNotIn(self.certo, r.context['bots_sugeridos'])
        self.assertNotIn(self.certo, r.context['bots_outros'])

    def test_bot_vinculado_e_clicavel_na_lista(self):
        self.projeto.bot = self.certo
        self.projeto.save()
        html = self.client.get('/ci/projects/').content.decode()
        self.assertIn(f'href="/bots/{self.certo.id}/"', html)
