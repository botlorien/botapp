#!/usr/bin/env bash
# Republica o histórico no GitHub depois que o repositório for recriado.
#
# Contexto: force push não expurga objeto inalcançável — o GitHub mantém
# commits antigos acessíveis por SHA direto até um GC que pode não rodar.
# Apagar e recriar o repositório é o que garante o expurgo.
#
# Rode DEPOIS de recriar o repositório vazio (sem README/.gitignore/licença).
#
# A lista de termos a barrar vem de `.termos-privados.txt` (um por linha, fora
# do versionamento). Ela NÃO pode ser escrita aqui: este arquivo é publicado, e
# um script que enumera o que não pode vazar vaza exatamente isso.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTO="${BOTAPP_REMOTO:-git@github.com:botlorien/botapp.git}"
LISTA="$REPO_DIR/.termos-privados.txt"
cd "$REPO_DIR"

verifica_historico() {  # $1 = diretório do repo a auditar
  if [ ! -f "$LISTA" ]; then
    echo "   aviso: $LISTA ausente — checagem de termos pulada"
    return 0
  fi
  local padrao
  padrao=$(grep -vE '^\s*(#|$)' "$LISTA" | paste -sd'|' -)
  git -C "$1" log --all -p --no-color 2>/dev/null | grep -icE "$padrao" || true
}

echo "== conferindo o histórico local antes de publicar =="
ENCONTRADOS=$(verifica_historico "$REPO_DIR")
if [ "${ENCONTRADOS:-0}" != "0" ]; then
  echo "ABORTADO: $ENCONTRADOS ocorrência(s) de termo privado no histórico local."
  exit 1
fi
echo "   ok — nenhum termo privado"

git remote set-url origin "$REMOTO" 2>/dev/null || git remote add origin "$REMOTO"
echo "== publicando =="
git push -u origin main
git push origin --tags

echo "== auditando o que o GitHub passou a servir =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git clone -q "$REMOTO" "$TMP/conferencia"
RESTOU=$(verifica_historico "$TMP/conferencia")
echo "   commits: $(git -C "$TMP/conferencia" log --oneline | wc -l)" \
     "| tags: $(git -C "$TMP/conferencia" tag | wc -l)"
echo "   autores: $(git -C "$TMP/conferencia" log --all --pretty=format:'%an' \
                    | sort -u | tr '\n' ' ')"
echo "   termos privados no remoto: ${RESTOU:-0}"
[ "${RESTOU:-0}" = "0" ] && echo "OK — repositório publicado limpo" || exit 1
