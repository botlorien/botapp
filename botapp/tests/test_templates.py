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
