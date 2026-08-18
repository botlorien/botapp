"""Visão geral de CI: coluna de situação e filtro com padrão 'ativos'."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from botapp.models import Bot, CIConnection, CIProject


@override_settings(BOTAPP_CI_ENABLED=True)
class VisaoGeralDeCI(TestCase):
    def setUp(self):
        agora = timezone.now()
        conexao = CIConnection.objects.create(
            name='c', base_url='https://exemplo.invalido', namespace='g',
            token_source='env', token_env_var='BOTAPP_CI_TOKEN')

        def projeto(caminho, bot, **extra):
            p = CIProject.objects.create(connection=conexao, path=f'g/{caminho}',
                                         name=caminho, bot=bot, monitored=True,
                                         external_id=abs(hash(caminho)) % 10000,
                                         last_pipeline_at=agora, **extra)
            return p

        self.bot_ativo = Bot.objects.create(name='bot vivo', description='d',
                                            version='1', is_active=True)
        self.bot_off = Bot.objects.create(name='bot desligado', description='d',
                                          version='1', is_active=False)
        # os três não instrumentaram (last_execution_at nulo)
        self.vivo = projeto('vivo', self.bot_ativo)
        self.arquivado = projeto('arquivado', self.bot_ativo, archived=True)
        self.bot_inativo = projeto('bot_off', self.bot_off)

        usuario = get_user_model().objects.create_user(
            'adm', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)

    def _caminhos(self, url):
        r = self.client.get(url)
        return sorted(p.path for p in r.context['sem_instrumentacao'])

    def test_padrao_lista_so_ativos(self):
        self.assertEqual(self._caminhos('/ci/'), ['g/vivo'])

    def test_inativos_isola_arquivado_e_bot_desligado(self):
        self.assertEqual(self._caminhos('/ci/?situacao=inativos'),
                         ['g/arquivado', 'g/bot_off'])

    def test_todos_traz_os_tres(self):
        self.assertEqual(self._caminhos('/ci/?situacao='),
                         ['g/arquivado', 'g/bot_off', 'g/vivo'])

    def test_contadores_seguem_o_filtro(self):
        """Contar projeto arquivado como monitorado infla o número: ele nem
        chega a ser sincronizado."""
        r = self.client.get('/ci/')
        self.assertEqual(r.context['total_monitorados'], 1)
        r = self.client.get('/ci/?situacao=')
        self.assertEqual(r.context['total_monitorados'], 3)

    def test_coluna_de_situacao_explica_o_motivo(self):
        html = self.client.get('/ci/?situacao=inativos').content.decode()
        self.assertIn('arquivado no servidor de CI', html)
        self.assertIn('bot desativado', html)

    def test_motivo_vazio_quando_ativo(self):
        self.assertEqual(self.vivo.motivo_inatividade, '')
        self.assertEqual(self.bot_inativo.motivo_inatividade, 'bot desativado')


class EstiloDoCheckbox(TestCase):
    def test_tema_claro_preserva_o_estado_marcado(self):
        """`:root[data-theme="light"] .fx-checkbox` tem especificidade MAIOR que
        `.fx-checkbox:checked`. Sem repetir o estado marcado no tema claro, o
        fundo azul some e o "✓" branco fica invisível sobre branco — a caixa
        marca e parece não marcar.
        """
        from pathlib import Path
        base = (Path(__file__).resolve().parent.parent / 'templates' / 'botapp'
                / 'base.html').read_text(encoding='utf-8')
        self.assertIn(':root[data-theme="light"] .fx-checkbox:checked', base)
