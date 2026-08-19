"""Guardas sobre o que os templates entregam à tela."""
import re
from pathlib import Path

from django.test import TestCase

TEMPLATES = sorted((Path(__file__).resolve().parent.parent
                    / 'templates' / 'botapp').glob('*.html'))


class ComentariosDeTemplate(TestCase):
    def test_comentario_curto_nao_atravessa_linhas(self):
        """`{# #}` do Django é de UMA linha — aberto numa e fechado noutra, ele
        deixa de ser comentário e o texto aparece na tela do usuário. Já
        aconteceu em produção; aqui a checagem é automática.
        """
        problemas = []
        for arquivo in TEMPLATES:
            for numero, linha in enumerate(arquivo.read_text(encoding='utf-8')
                                           .splitlines(), 1):
                if linha.count('{#') != linha.count('#}'):
                    problemas.append(f'{arquivo.name}:{numero}')
        self.assertEqual(problemas, [],
                         f'comentário {{# #}} aberto e não fechado na mesma '
                         f'linha (usar {{% comment %}} para várias): {problemas}')

    def test_sem_marcador_de_template_orfao(self):
        """`{%` sem fechar na mesma linha também vaza como texto."""
        problemas = []
        for arquivo in TEMPLATES:
            texto = arquivo.read_text(encoding='utf-8')
            for numero, linha in enumerate(texto.splitlines(), 1):
                if re.search(r'\{%(?![^%]*%\})', linha):
                    problemas.append(f'{arquivo.name}:{numero}')
        self.assertEqual(problemas, [], f'tag de template sem fechamento na '
                                        f'mesma linha: {problemas}')


class CookiesComNomeProprio(TestCase):
    """Atrás de um proxy same-origin, o Domain some e os cookies de todas as
    aplicações caem no host do proxy com Path=/. Com os nomes default do Django
    elas se sobrescrevem: csrftoken trocado vira 403 em toda mutação, sessionid
    trocado derruba a sessão. Isso aconteceu em produção."""

    def test_nomes_nao_sao_os_defaults_do_django(self):
        from django.conf import settings
        self.assertNotEqual(settings.CSRF_COOKIE_NAME, 'csrftoken')
        self.assertNotEqual(settings.SESSION_COOKIE_NAME, 'sessionid')

    def test_front_nao_le_o_cookie_pelo_nome(self):
        """O JS lia /csrftoken=([^;]+)/ do document.cookie — acoplado ao nome e
        capaz de pegar o cookie de outra aplicação no mesmo host."""
        for arquivo in TEMPLATES:
            texto = arquivo.read_text(encoding='utf-8')
            self.assertNotIn('document.cookie.match', texto,
                             f'{arquivo.name} ainda lê o cookie direto')
