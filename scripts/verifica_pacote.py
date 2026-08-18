#!/usr/bin/env python3
"""Confere o que o pacote realmente leva, ANTES de publicar.

Este é um pacote público: o que entra no sdist/wheel vira permanente. O PyPI
não deixa substituir uma versão — só publicar outra ou remover a antiga, e
remover não alcança mirrors nem caches. Por isso a checagem é antes.

    python scripts/verifica_pacote.py dist/

O que é verificado:
  * bytecode (.pyc) embarcado — grava o caminho ABSOLUTO da máquina que
    compilou, expondo usuário e estrutura de pastas de quem publicou;
  * caminho absoluto em qualquer arquivo, pela mesma razão;
  * string com forma de credencial;
  * termos privados que você não quer publicar: um por linha em
    `.termos-privados.txt` na raiz (fora do versionamento). Sem o arquivo,
    essa checagem é pulada — a lista é sua, não do pacote.

Sai com código != 0 se achar algo, para travar a publicação no CI.
"""
import io
import re
import sys
import tarfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

SUSPEITAS = [
    ('bytecode embarcado', re.compile(r'\.py[co]$'), 'nome'),
    ('caminho absoluto', re.compile(
        r'[A-Za-z]:\\Users\\|/home/[a-z0-9_-]+/|/Users/[a-z0-9_-]+/'), 'conteudo'),
    ('token de CI', re.compile(r'gl(pat|rt)-[A-Za-z0-9_\-]{15,}'), 'conteudo'),
    ('chave AWS', re.compile(r'AKIA[0-9A-Z]{16}'), 'conteudo'),
    ('token GitHub', re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'), 'conteudo'),
    ('chave privada', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
     'conteudo'),
    # exclui `\`, `{`, `[`, `$` no lugar da senha: isso é template, placeholder
    # ou referência a variável — a própria regra de redação casa aqui, e um
    # alerta que grita à toa acaba ignorado justamente quando for verdadeiro
    ('credencial em URL',
     re.compile(r'://[^/\s:@{}\[\]\\$]+:[^/\s:@{}\[\]\\$]{6,}@'), 'conteudo'),
]


def termos_privados():
    arquivo = RAIZ / '.termos-privados.txt'
    if not arquivo.exists():
        return None
    termos = [l.strip() for l in arquivo.read_text(encoding='utf-8').splitlines()
              if l.strip() and not l.startswith('#')]
    return re.compile('|'.join(re.escape(t) for t in termos), re.IGNORECASE)


def conteudo_do_pacote(caminho):
    bruto = caminho.read_bytes()
    if caminho.suffix == '.whl':
        z = zipfile.ZipFile(io.BytesIO(bruto))
        for nome in z.namelist():
            yield nome, z.read(nome)
    else:
        t = tarfile.open(fileobj=io.BytesIO(bruto))
        for membro in t.getmembers():
            if membro.isfile():
                yield membro.name, t.extractfile(membro).read()


def main(destino):
    pacotes = sorted(p for p in Path(destino).iterdir()
                     if p.suffix in ('.whl', '.gz'))
    if not pacotes:
        print(f'nenhum pacote em {destino}')
        return 1

    privados = termos_privados()
    if privados is None:
        print('aviso: .termos-privados.txt ausente — checagem de termos pulada')

    problemas = []
    for pacote in pacotes:
        print(f'\n{pacote.name}')
        arquivos = 0
        for nome, corpo in conteudo_do_pacote(pacote):
            arquivos += 1
            texto = corpo.decode('utf-8', errors='ignore')
            for rotulo, regex, onde in SUSPEITAS:
                alvo = nome if onde == 'nome' else texto
                achado = regex.search(alvo)
                if achado:
                    problemas.append((pacote.name, nome, rotulo,
                                      achado.group(0)[:60]))
            if privados:
                achado = privados.search(texto) or privados.search(nome)
                if achado:
                    problemas.append((pacote.name, nome, 'termo privado',
                                      achado.group(0)))
        print(f'  {arquivos} arquivo(s) inspecionado(s)')

    if not problemas:
        print('\nOK — nada suspeito no que vai ser publicado')
        return 0

    print(f'\n{len(problemas)} PROBLEMA(S) — publicação deve ser abortada:')
    for pacote, arquivo, rotulo, trecho in problemas:
        print(f'  [{rotulo}] {pacote} :: {arquivo}\n      {trecho}')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'dist'))
