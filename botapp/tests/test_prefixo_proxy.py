"""Embed sob reverse-proxy same-origin: a URL que o JS monta tem de resolver.

Atrás do proxy da intranet (``/botapp-app``) o Django recebe
``X-Forwarded-Prefix`` e o ``ForwardedPrefixMiddleware`` seta ``SCRIPT_NAME``.
A partir daí ``{% url %}``/``reverse()`` JÁ devolvem o caminho **prefixado**.
Se o ``bpUrl()`` do front prefixar de novo, a chamada vira
``/botapp-app/botapp-app/...`` e o servidor responde **404**.

Foi o que aconteceu com o badge de alertas: a tela listava 9 alertas ativos e o
número vermelho no botão nunca aparecia — o ``fetch`` caía no
``if (!r.ok) return;`` e ninguém via erro. Os outros ``bpUrl()`` do front
passam caminho literal (``/alerts/<id>/ack/``), por isso só os três que
compunham ``bpUrl('{% url %}')`` quebravam.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_script_prefix

from botapp.models import Alert

PREFIXO = '/botapp-app'
BASE_HTML = (Path(__file__).resolve().parent.parent
             / 'templates' / 'botapp' / 'base.html')


def _bpurl_do_template() -> str:
    """Devolve o corpo JS do ``window.bpUrl`` exatamente como é servido."""
    texto = BASE_HTML.read_text(encoding='utf-8')
    m = re.search(r'window\.bpUrl\s*=\s*function[\s\S]*?\n(?=\s*//|\s*\()',
                  texto)
    assert m, 'window.bpUrl não encontrado em base.html'
    return m.group(0)


class UrlDoTemplateSobPrefixo(TestCase):
    """O lado servidor: com SCRIPT_NAME, `{% url %}` já sai prefixado.

    O ``ClientHandler`` de teste não chama ``set_script_prefix`` (só o
    ``WSGIHandler`` real chama), então o prefixo entra por
    ``override_script_prefix`` — é o que o gunicorn faz em produção a partir do
    ``SCRIPT_NAME`` que o ``ForwardedPrefixMiddleware`` grava no environ.
    """

    def setUp(self):
        usuario = get_user_model().objects.create_user(
            'operador', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(usuario)
        Alert.objects.create(type=Alert.Type.PIPELINE_FAILED,
                             severity=Alert.Severity.HIGH,
                             message='pipeline falhou')

    @override_script_prefix(PREFIXO + '/')
    def test_url_renderizada_ja_traz_o_prefixo(self):
        html = self.client.get('/alerts/', SCRIPT_NAME=PREFIXO).content.decode()
        self.assertIn(f'{PREFIXO}/alerts/unread-count/', html,
                      'o {% url %} deveria sair prefixado sob SCRIPT_NAME')
        self.assertNotIn(f'{PREFIXO}{PREFIXO}/', html,
                         'nenhuma URL do HTML pode vir com prefixo dobrado')

    def test_caminho_com_prefixo_dobrado_nao_existe(self):
        """É o 404 que o navegador recebia — e que o front engolia."""
        dobrado = self.client.get(f'{PREFIXO}/alerts/unread-count/',
                                  SCRIPT_NAME=PREFIXO)
        self.assertEqual(dobrado.status_code, 404)

        correto = self.client.get('/alerts/unread-count/', SCRIPT_NAME=PREFIXO)
        self.assertEqual(correto.status_code, 200)
        self.assertEqual(json.loads(correto.content)['count'], 1)


class BpUrlNaoDuplicaPrefixo(TestCase):
    """O lado cliente: roda o JS real de base.html, não uma reimplementação."""

    def _bpurl(self, caminho: str) -> str:
        node = shutil.which('node')
        if not node:
            self.skipTest('node não disponível para executar o JS do template')
        script = (
            'var window = {BOTAPP_PREFIX: ' + json.dumps(PREFIXO) + '};\n'
            + _bpurl_do_template()
            + '\nconsole.log(window.bpUrl(' + json.dumps(caminho) + '));\n'
        )
        saida = subprocess.run([node, '-e', script], capture_output=True,
                               text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        return saida.stdout.strip()

    def test_caminho_sem_prefixo_recebe_o_prefixo(self):
        self.assertEqual(self._bpurl('/alerts/unread-count/'),
                         f'{PREFIXO}/alerts/unread-count/')

    def test_caminho_ja_prefixado_fica_como_esta(self):
        """É o caso do `{% url %}` sob SCRIPT_NAME — prefixar de novo dá 404."""
        self.assertEqual(self._bpurl(f'{PREFIXO}/alerts/unread-count/'),
                         f'{PREFIXO}/alerts/unread-count/')

    def test_o_proprio_prefixo_nao_dobra(self):
        self.assertEqual(self._bpurl(PREFIXO), PREFIXO)
