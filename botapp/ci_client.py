"""Cliente de leitura para servidor de CI (hoje: GitLab).

GENÉRICO por obrigação: este arquivo vai para um pacote público, então nenhuma
URL, grupo, projeto ou token de qualquer organização aparece aqui — tudo vem de
configuração. Ver docs/ci-integration-design.md.

O cliente é somente-leitura: não existe método que dispare pipeline, altere
agendamento ou escreva qualquer coisa no servidor de CI.
"""
import hashlib
import logging
import os
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# O GitLab limita per_page (tipicamente 100). Pedir mais NÃO devolve mais e NÃO
# dá erro — devolve o máximo em silêncio, e quem confia no número que pediu
# conclui que o resto não existe. Já custou um diagnóstico errado.
PER_PAGE_MAX = 100

def timeout_default():
    try:
        return max(5, int(os.getenv('BOTAPP_CI_TIMEOUT_SECONDS', '30')))
    except ValueError:
        return 30


def allow_insecure():
    """Lida em tempo de chamada de propósito: se fosse constante de import,
    mudar a variável exigiria reiniciar o processo."""
    return os.getenv('BOTAPP_CI_ALLOW_INSECURE', 'false').strip().lower() == 'true'


class CIError(Exception):
    """Falha ao falar com o servidor de CI."""


class CIConfigError(CIError):
    """Configuração inválida (URL, token, escopo)."""


def fingerprint(token):
    """Identifica um token sem revelá-lo. Nunca logue/exiba o token em si."""
    if not token:
        return ''
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def resolve_token(connection):
    """Devolve o token da conexão, sem nunca persistir nem logar o valor.

    `env` é o modo recomendado: o banco guarda só o NOME da variável, então um
    dump de backup não contém credencial. `db` existe para múltiplas conexões e
    exige BOTAPP_CI_TOKEN_KEY — na ausência dela é RECUSADO, em vez de guardar
    em texto puro.
    """
    if connection.token_source == 'env':
        nome = (connection.token_env_var or 'BOTAPP_CI_TOKEN').strip()
        token = os.getenv(nome, '').strip()
        if not token:
            raise CIConfigError(
                f'variável de ambiente {nome} vazia ou ausente — a conexão '
                f'"{connection.name}" não tem token para usar')
        return token

    chave = os.getenv('BOTAPP_CI_TOKEN_KEY', '').strip()
    if not chave:
        raise CIConfigError(
            'token_source="db" exige BOTAPP_CI_TOKEN_KEY (chave Fernet). '
            'Sem ela o token não é gravado em texto puro — configure a chave '
            'ou use token_source="env".')
    if not connection.token_encrypted:
        raise CIConfigError(f'conexão "{connection.name}" sem token gravado')
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:  # pragma: no cover - depende de extra opcional
        raise CIConfigError(
            'token_source="db" requer o extra de criptografia: '
            'pip install "botapp[ci-db-token]"') from e
    try:
        return Fernet(chave.encode()).decrypt(bytes(connection.token_encrypted)).decode()
    except Exception as e:
        raise CIConfigError('não consegui decifrar o token gravado — a chave '
                            'BOTAPP_CI_TOKEN_KEY mudou?') from e


def encrypt_token(valor):
    """Cifra um token para gravar no banco (modo `db`)."""
    chave = os.getenv('BOTAPP_CI_TOKEN_KEY', '').strip()
    if not chave:
        raise CIConfigError('BOTAPP_CI_TOKEN_KEY ausente — não gravo token em '
                            'texto puro')
    from cryptography.fernet import Fernet
    return Fernet(chave.encode()).encrypt(valor.encode())


class GitLabClient:
    """Leitura de projetos, agendamentos, pipelines, jobs e logs."""

    def __init__(self, base_url, token, timeout=None, session=None):
        self.base_url = self._validar_base_url(base_url)
        self._token = token
        self.timeout = timeout or timeout_default()
        self.session = session or requests.Session()

    @staticmethod
    def _validar_base_url(base_url):
        """Recusa esquema inseguro e URL sem host — a URL vem de configuração,
        então é entrada não confiável (superfície de SSRF)."""
        url = (base_url or '').strip().rstrip('/')
        if not url:
            raise CIConfigError('base_url vazia')
        p = urlparse(url)
        if not p.netloc:
            raise CIConfigError(f'base_url sem host: {url!r}')
        if p.scheme == 'http' and not allow_insecure():
            raise CIConfigError(
                'base_url em http:// — o token viajaria em claro. Use https ou '
                'defina BOTAPP_CI_ALLOW_INSECURE=true assumindo o risco.')
        if p.scheme not in ('http', 'https'):
            raise CIConfigError(f'esquema não suportado: {p.scheme!r}')
        return url

    # ── HTTP ───────────────────────────────────────────────────────────────
    def _request(self, caminho, params=None, stream=False, tentativas=3):
        url = f'{self.base_url}/api/v4{caminho}'
        cab = {'PRIVATE-TOKEN': self._token}
        ultimo_erro = None
        for tentativa in range(1, tentativas + 1):
            try:
                r = self.session.get(url, headers=cab, params=params,
                                     timeout=self.timeout, stream=stream,
                                     allow_redirects=False)
            except requests.RequestException as e:
                # a mensagem de erro do requests pode ecoar cabeçalhos: nunca
                # repasse a exceção crua para o log
                ultimo_erro = f'{type(e).__name__}: {self._mascarar(str(e))}'
                if tentativa < tentativas:
                    time.sleep(min(2 ** tentativa, 8))
                    continue
                raise CIError(f'falha de rede em {caminho}: {ultimo_erro}') from None

            if r.status_code in (301, 302, 303, 307, 308):
                # não seguimos redirect: destino pode ser outro host e levaria o
                # token junto
                raise CIError(f'{caminho} respondeu redirecionamento para outro '
                              f'host; recusado por segurança')
            if r.status_code == 429 and tentativa < tentativas:
                espera = int(r.headers.get('Retry-After', 2 ** tentativa))
                time.sleep(min(espera, 30))
                continue
            if r.status_code >= 500 and tentativa < tentativas:
                time.sleep(min(2 ** tentativa, 8))
                continue
            if r.status_code == 401:
                raise CIConfigError(f'401 em {caminho}: token inválido ou expirado')
            if r.status_code == 403:
                raise CIConfigError(
                    f'403 em {caminho}: token sem permissão de leitura para este '
                    f'recurso (escopo insuficiente ou recurso de instância)')
            if r.status_code >= 400:
                raise CIError(f'HTTP {r.status_code} em {caminho}: '
                              f'{self._mascarar(r.text[:200])}')
            return r
        raise CIError(f'esgotei as tentativas em {caminho}: {ultimo_erro}')

    def _mascarar(self, texto):
        """Garante que o token não escape em mensagem de erro/log."""
        if self._token and self._token in texto:
            texto = texto.replace(self._token, '***')
        return texto

    def _paginado(self, caminho, params=None, limite=None):
        """Itera todas as páginas. per_page é FIXADO no máximo permitido."""
        params = dict(params or {})
        params['per_page'] = PER_PAGE_MAX
        pagina, total = 1, 0
        while True:
            params['page'] = pagina
            r = self._request(caminho, params=params)
            lote = r.json()
            if not isinstance(lote, list):
                raise CIError(f'{caminho} devolveu {type(lote).__name__}, '
                              f'esperava lista')
            for item in lote:
                yield item
                total += 1
                if limite and total >= limite:
                    return
            # o header é a fonte da verdade da paginação; contar itens do lote
            # falha quando o total é múltiplo exato de per_page
            proxima = r.headers.get('X-Next-Page') or ''
            if not proxima.strip():
                return
            pagina = int(proxima)

    # ── leitura ────────────────────────────────────────────────────────────
    def testar_conexao(self):
        """Confirma credencial + alcance do namespace. Devolve resumo curto."""
        v = self._request('/version').json()
        return {'version': v.get('version', '?'), 'revision': v.get('revision', '')}

    def projetos(self, namespace, incluir_arquivados=False):
        """Projetos do grupo, com subgrupos.

        Endpoint de GRUPO de propósito: os equivalentes de instância (ex.: listar
        todos os runners) exigem admin e devolvem 403 para token comum.
        """
        params = {'include_subgroups': 'true',
                  'archived': 'true' if incluir_arquivados else 'false',
                  'order_by': 'path', 'sort': 'asc'}
        return self._paginado(f'/groups/{self._q(namespace)}/projects', params)

    def agendamentos(self, project_id):
        return self._paginado(f'/projects/{project_id}/pipeline_schedules')

    def pipelines(self, project_id, updated_after=None, limite=None):
        params = {'order_by': 'updated_at', 'sort': 'desc'}
        if updated_after:
            params['updated_after'] = updated_after
        return self._paginado(f'/projects/{project_id}/pipelines', params,
                              limite=limite)

    def pipeline(self, project_id, pipeline_id):
        return self._request(f'/projects/{project_id}/pipelines/{pipeline_id}').json()

    def jobs(self, project_id, pipeline_id):
        return self._paginado(
            f'/projects/{project_id}/pipelines/{pipeline_id}/jobs')

    def trace(self, project_id, job_id, max_bytes=None):
        """Log de um job. Trunca no tamanho pedido — trace de CI passa de 1 MB.

        Devolve (texto, truncado_no_inicio). Quando trunca, mantém o FIM: é onde
        está o traceback e o motivo da falha.
        """
        r = self._request(f'/projects/{project_id}/jobs/{job_id}/trace', stream=True)
        if max_bytes is None:
            texto = r.text
            return texto, False
        pedacos, tamanho = [], 0
        for pedaco in r.iter_content(chunk_size=8192):
            if not pedaco:
                continue
            pedacos.append(pedaco)
            tamanho += len(pedaco)
            # mantém uma janela deslizante do fim, sem carregar tudo em memória
            while tamanho > max_bytes * 2 and len(pedacos) > 1:
                tamanho -= len(pedacos.pop(0))
        bruto = b''.join(pedacos)
        truncado = len(bruto) > max_bytes
        if truncado:
            bruto = bruto[-max_bytes:]
        return bruto.decode('utf-8', errors='replace'), truncado

    def trace_stream(self, project_id, job_id, chunk_size=8192):
        """Gera o log em pedaços, para transmitir sem materializar em memória."""
        r = self._request(f'/projects/{project_id}/jobs/{job_id}/trace', stream=True)
        for pedaco in r.iter_content(chunk_size=chunk_size):
            if pedaco:
                yield pedaco

    @staticmethod
    def _q(valor):
        """Namespace pode ser id numérico ou path com barras (precisa escapar)."""
        from urllib.parse import quote
        valor = str(valor).strip()
        return valor if valor.isdigit() else quote(valor, safe='')


def client_for(connection):
    """Cliente pronto a partir de um registro de conexão."""
    if connection.kind != 'gitlab':
        raise CIConfigError(f'provedor não implementado: {connection.kind!r}')
    return GitLabClient(connection.base_url, resolve_token(connection))
