"""Testes da tela inicial de bots: padrão do filtro e ordem dos cards.

Os dois comportamentos aqui são de tela, não de modelo — por isso vão pelo
cliente HTTP, olhando o que o operador de fato recebe.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from botapp.models import Bot


class TelaDeBots(TestCase):
    def setUp(self):
        agora = timezone.now()
        self.recente = Bot.objects.create(name='bot recente', description='x',
                                          version='1', is_active=True)
        Bot.objects.filter(pk=self.recente.pk).update(last_execution_at=agora)

        self.antigo = Bot.objects.create(name='bot antigo', description='x',
                                         version='1', is_active=True)
        Bot.objects.filter(pk=self.antigo.pk).update(
            last_execution_at=agora - timedelta(days=30))

        # o caso do relato: cadastrado, ativo, nunca executou
        self.nunca_rodou = Bot.objects.create(name='bot que nunca rodou',
                                              description='x', version='1',
                                              is_active=True)

        self.inativo = Bot.objects.create(name='bot inativo', description='x',
                                          version='1', is_active=False)
        Bot.objects.filter(pk=self.inativo.pk).update(last_execution_at=agora)

        usuario = get_user_model().objects.create_user(
            'operador', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)

    def _nomes(self, url):
        """Nomes na ordem em que aparecem na página."""
        html = self.client.get(url).content.decode()
        posicoes = sorted((html.index(b.name), b.name)
                          for b in Bot.objects.all() if b.name in html)
        return [nome for _, nome in posicoes]

    def test_sem_parametro_lista_so_ativos(self):
        """Entrar na tela sem filtrar já traz só os ativos."""
        nomes = self._nomes('/bots/')
        self.assertNotIn('bot inativo', nomes)
        self.assertIn('bot recente', nomes)

    def test_todos_continua_possivel(self):
        """A chave vazia é a escolha explícita "Todos" — precisa vencer o padrão."""
        nomes = self._nomes('/bots/?is_active=')
        self.assertIn('bot inativo', nomes)
        self.assertIn('bot recente', nomes)

    def test_filtro_de_inativos(self):
        nomes = self._nomes('/bots/?is_active=false')
        self.assertEqual(nomes, ['bot inativo'])

    def test_select_reflete_o_padrao(self):
        """Se a tela filtra por ativos, o campo tem de dizer isso."""
        html = self.client.get('/bots/').content.decode()
        self.assertIn('<option value="true"  selected>Ativos</option>', html)

    def test_quem_nunca_executou_vai_para_o_fim(self):
        """last_execution_at nulo não pode se passar por execução recente."""
        nomes = self._nomes('/bots/')
        self.assertEqual(nomes,
                         ['bot recente', 'bot antigo', 'bot que nunca rodou'])

    def test_ordem_e_explicita_no_sql(self):
        """O teste acima passaria mesmo sem a correção, porque o SQLite já põe
        NULL por último em DESC. O Postgres — que é o banco de produção — põe
        NULL PRIMEIRO. Só o "NULLS LAST" explícito garante a ordem nos dois.
        """
        from django.test import RequestFactory

        from botapp.views import filter_bots
        requisicao = RequestFactory().get('/bots/')
        requisicao.user = get_user_model().objects.get(username='operador')
        sql = str(filter_bots(requisicao).query).upper()
        self.assertIn('NULLS LAST', sql)
