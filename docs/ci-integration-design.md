# Integração com CI (GitLab) — desenho

> Status: **proposta**. Nada implementado ainda. Este documento é a referência de
> arquitetura da feature; ele fica no repositório público e por isso é
> **inteiramente genérico** — nenhuma URL, id de grupo, nome de projeto ou
> credencial de qualquer organização aparece aqui, nem deve aparecer no código.

## 1. Problema

Hoje o botapp só conhece o que o bot conta sobre si mesmo: o SDK chama
`set_bot` / `run_task` e grava `Bot`, `Task`, `TaskLog`. Isso cobre bem o que
acontece **dentro** do processo, mas deixa três pontos cegos:

1. **Bot que nunca chega a instrumentar.** Se o processo morre antes do
   `run_task` — falha de credencial, dependência ausente, imagem quebrada — o
   painel não mostra nada. O bot aparece como silencioso, indistinguível de um
   bot que simplesmente não tinha o que fazer.
2. **Bot fora da telemetria.** Um bot cujo SDK não está configurado (falta env,
   por exemplo) roda, falha e ninguém vê. Não há como o painel saber que ele
   existe.
3. **Verde que mente.** Pipeline que termina com sucesso mas cujo log tem
   `Traceback` — o processo engoliu a exceção e saiu com código 0. O status do
   CI diz OK; o trabalho não aconteceu.

Os três se resolvem olhando o CI, não o bot: a plataforma sabe que o job existiu,
qual foi o status e o que saiu no log — mesmo quando o bot não conseguiu dizer
nada.

## 2. Escopo

Ler de um servidor de CI, por token de leitura:

- **projetos** de um namespace/grupo (com refresh periódico)
- **agendamentos** de cada projeto (cron, timezone, ativo, próxima execução)
- **pipelines** (status, origem, ref, duração, quem disparou)
- **jobs** de cada pipeline e, **sob demanda**, o log de execução

E derivar telemetria/alertas disso. Escrita no CI (disparar pipeline, editar
agendamento) está **fora de escopo** nesta fase — o token deve ser somente de
leitura, e o valor está em observar.

## 3. Princípio: genérico no pacote, específico no ambiente

O pacote é publicado publicamente. Portanto:

| regra | consequência prática |
|---|---|
| Nenhum default aponta para uma organização | `BOTAPP_CI_BASE_URL` **não** tem default; sem ela a feature fica desligada |
| Nenhum nome de projeto/grupo no código | namespace vem de env ou do registro no banco |
| Nenhum segredo no repositório, nos fixtures ou nos testes | testes usam servidor fake local |
| Nada de vocabulário interno de uma empresa | modelos e telas falam "project", "pipeline", "schedule" |
| Padrões de erro configuráveis | a lista default é genérica (`Traceback`, `Exception`), não a de um cliente |

Quem usa o pacote configura por variável de ambiente e pela tela. **Toda**
customização corporativa vive fora deste repositório.

## 4. Modelo de dados

Novos modelos no app `botapp` (migração `0013`), com `kind` desde o início para
que suportar outro provedor depois não exija mudança de schema — mas apenas o
cliente GitLab é implementado agora.

```
CIConnection
  kind            'gitlab' (choices; único valor implementado)
  name            rótulo livre
  base_url        URL do servidor de CI            <- sem default
  namespace       grupo/org a sincronizar (path ou id, string)
  token_source    'env' | 'db'                     <- ver §5
  token_env_var   nome da env var quando source='env'
  token_encrypted campo binário, só quando source='db'
  enabled         bool
  last_sync_at / last_sync_status / last_sync_error
  discovery_interval_minutes   (default 1440)
  poll_interval_minutes        (default 15)

CIProject
  connection      FK
  external_id     id no provedor        (unique_together com connection)
  path, name, web_url, default_branch, archived
  monitored       bool  — só projeto monitorado gera pipeline/telemetria
  bot             FK nullable -> Bot    — une as duas visões (§7)
  scan_logs       bool  — habilita a detecção de "verde que mente" (§6.3)
  last_pipeline_* denormalizado p/ listagem sem N+1

CISchedule
  project FK, external_id, description, cron, cron_timezone,
  active, next_run_at, last_pipeline_external_id

CIPipeline
  project FK, external_id (unique com project), iid
  status, source, ref, sha, commit_title, web_url
  created_at, started_at, finished_at, duration
  schedule FK nullable
  triggered_by    string (username) — ver nota de privacidade em §5

CIJob
  pipeline FK, external_id, name, stage, status
  runner_description, started_at, finished_at, duration
  failure_reason, web_url
  log_excerpt     TextField null — só cauda, só em falha/suspeita (§6.3)
  log_excerpt_at  quando foi capturado
```

**Por que denormalizar `last_pipeline_*` no projeto:** a listagem é a tela mais
acessada e sem isso ela faz uma subquery por linha. O `Bot` já usa essa mesma
estratégia (`last_execution_at`, `last_status`), então é coerente.

**Por que não guardar log inteiro:** um trace de CI passa fácil de 1 MB, e há
jobs de build que passam de 50 MB. Guardar tudo transformaria o banco do painel
num repositório de logs, com custo e risco desproporcionais (§5). O log completo
é buscado **sob demanda** e transmitido; só a **cauda** de jobs com falha ou
suspeita é persistida, com limite de tamanho.

## 5. Segurança

O ponto mais sensível da feature é o token: ele lê **todos** os repositórios do
namespace, incluindo código e logs de build.

**Onde o token mora.** Duas fontes, e a primeira é o default recomendado:

1. **`token_source='env'` (recomendado).** O token nunca entra no banco. O
   registro guarda apenas o **nome** da env var; o valor é lido do ambiente do
   processo. Vantagem: quem já gerencia segredos por variável de CI/secret
   manager continua com uma única fonte da verdade, e um dump do banco não
   contém credencial.
2. **`token_source='db'` (opcional).** Necessário quando há várias conexões e o
   operador não pode criar uma env var por conexão. Nesse caso o valor é
   cifrado com uma chave vinda de `BOTAPP_CI_TOKEN_KEY` (Fernet). **Sem essa
   env var, esse modo é recusado** — em vez de guardar em texto puro.

**Invariantes, valendo para os dois modos:**

- o token **nunca** é serializado por nenhum endpoint da API;
- a tela mostra no máximo um *fingerprint* (hash curto) e o resultado do último
  teste de conexão — nunca o valor, nem parcialmente;
- o token não vai para log, nem em nível DEBUG; o cliente HTTP mascara o header
  de autorização ao registrar erro;
- o formulário grava, mas nunca **lê de volta** o valor (campo write-only).

**Escopo mínimo do token.** Só leitura de API. Documentar explicitamente que um
token de leitura de API já dá acesso a **código-fonte e logs** do namespace — a
recomendação é um token de **grupo/serviço** com escopo de leitura, nunca um
token pessoal de administrador.

**Logs podem conter segredo.** A plataforma mascara variáveis marcadas como
*masked*, mas nada garante que um script não imprima um valor por conta própria.
Consequências no desenho: a exibição do log exige usuário autenticado, respeita
o escopo por departamento (§7), a cauda persistida tem limite de tamanho e pode
ser desligada por projeto (`scan_logs=False`), e o log completo não é armazenado.

**Privacidade (`triggered_by`).** Guardar quem disparou o pipeline é dado
pessoal de colaborador. Fica opcional por env (`BOTAPP_CI_STORE_TRIGGERED_BY`,
default **desligado**) para que a instalação decida — algumas jurisdições tratam
isso como monitoramento de pessoa, não de sistema.

**SSRF.** `base_url` é configurável, então o cliente valida esquema (`https`
por default, `http` só se `BOTAPP_CI_ALLOW_INSECURE=true`) e recusa redirecionar
para host diferente do configurado.

## 6. Sincronização

Um comando por responsabilidade, no padrão do `check_alerts` /
`run_alert_scheduler` que já existe:

- `sync_ci_projects` — descobre projetos e agendamentos (intervalo largo)
- `sync_ci_pipelines` — busca pipelines novos dos projetos monitorados
- `run_ci_scheduler` — loop que chama os dois nos respectivos intervalos

### 6.1 Incremental, com cursor por projeto

Pipelines são buscados por `updated_after = último cursor` e deduplicados por
`(project, external_id)`. Sem isso, cada ciclo relê a história inteira.

### 6.2 Erros isolados por projeto

Uma falha em um projeto (403, projeto arquivado, timeout) **não** aborta o
ciclo: registra em `last_sync_error` daquele projeto e segue. O ciclo só falha
inteiro se a conexão em si estiver inválida.

### 6.3 Detecção de "verde que mente" (opt-in por projeto)

Para projeto com `scan_logs=True`, ao ver um pipeline **com sucesso** o sync
busca o log dos jobs e procura padrões de erro. Achou → cria alerta e guarda a
cauda do log.

Isso custa uma chamada de log por job bem-sucedido, e é justamente por isso que
é **opt-in**: em instalação grande, ligar para tudo multiplica o tráfego. Os
padrões vêm de `BOTAPP_CI_ERROR_PATTERNS` (default genérico:
`Traceback (most recent call last)`, `Exception`, `FATAL`), e há
`BOTAPP_CI_IGNORE_PATTERNS` para os ruídos conhecidos de cada stack — sem essa
segunda lista a detecção vira alarme constante e é desligada por quem a usa.

### 6.4 Armadilhas conhecidas da API (custaram tempo, ficam registradas)

- **Paginação**: `per_page` é limitado (tipicamente 100). Pedir 200 **não**
  devolve 200 nem dá erro — devolve 100, e quem confia no número conclui que o
  resto não existe.
- **Endpoints de escopo global** (ex.: listar todos os runners) exigem admin de
  instância; usar sempre o escopo de grupo.
- **Busca em conteúdo de arquivo** costuma exigir plano pago; não depender dela.
- **Agendamento com variável pode não disparar** em algumas versões: o
  agendamento existe, está ativo, e nenhum pipeline nasce. Daí a regra de alerta
  `schedule_without_run` (§7) ter valor real.

## 7. Telemetria, alertas e união com `Bot`

Os alertas reusam o modelo `Alert` existente, com novos tipos:

| tipo | dispara quando |
|---|---|
| `pipeline_failed` | pipeline de projeto monitorado falhou |
| `pipeline_masked_error` | pipeline verde com padrão de erro no log (§6.3) |
| `schedule_without_run` | agendamento ativo sem pipeline há mais de N intervalos |
| `project_never_ran` | projeto monitorado sem nenhum pipeline registrado |

Reusar `Alert` traz de graça o *ack*/resolve, a contagem de não lidos e os
notificadores já existentes.

**A união com `Bot`** é o que fecha o ponto cego 2 do §1: com `CIProject.bot`
preenchido, o painel do bot passa a mostrar as duas visões lado a lado — o que o
SDK contou e o que o CI observou. Quando o CI registra execução e o SDK não, a
conclusão é direta: **o bot rodou e não instrumentou**. Hoje isso é invisível.

O vínculo pode ser sugerido automaticamente por semelhança de nome
(`Bot.name` × `CIProject.path`), mas a confirmação é manual — casar por
heurística e errar produziria telemetria atribuída ao bot errado, que é pior do
que não casar.

**Escopo por departamento** continua valendo: o módulo de scoping filtra por
`Bot.department`, então a visão de CI de um projeto vinculado herda o
departamento do bot. Projeto sem vínculo aparece só para staff.

## 8. Telas

| rota | conteúdo |
|---|---|
| `/ci/` | conexões: estado, último sync, botão "testar conexão" |
| `/ci/projects/` | projetos com filtro, toggle de monitoramento, vínculo com bot |
| `/ci/projects/<id>/` | agendamentos + pipelines recentes do projeto |
| `/ci/pipelines/<id>/` | jobs, status, duração e acesso ao log |
| `/ci/jobs/<id>/log` | log transmitido sob demanda (nunca com o token no cliente) |

O log é **proxeado** pelo servidor: o navegador nunca recebe o token. Resposta
transmitida em pedaços, com limite de bytes e `Content-Type` de texto puro para
não abrir espaço para XSS via conteúdo de log.

## 9. Variáveis de ambiente

Todas com prefixo `BOTAPP_CI_`, todas opcionais, e **nenhuma com default
apontando para qualquer servidor**:

| variável | default | função |
|---|---|---|
| `BOTAPP_CI_ENABLED` | `false` | liga a feature |
| `BOTAPP_CI_BASE_URL` | — | URL do servidor de CI |
| `BOTAPP_CI_NAMESPACE` | — | grupo/org a sincronizar |
| `BOTAPP_CI_TOKEN` | — | token de leitura (modo `env`) |
| `BOTAPP_CI_TOKEN_KEY` | — | chave Fernet (só p/ modo `db`) |
| `BOTAPP_CI_DISCOVERY_INTERVAL_MINUTES` | `1440` | refresh de projetos/agendamentos |
| `BOTAPP_CI_POLL_INTERVAL_MINUTES` | `15` | busca de pipelines |
| `BOTAPP_CI_ERROR_PATTERNS` | genérico | padrões de erro no log |
| `BOTAPP_CI_IGNORE_PATTERNS` | vazio | ruídos a ignorar |
| `BOTAPP_CI_LOG_TAIL_BYTES` | `65536` | tamanho máx. da cauda persistida |
| `BOTAPP_CI_STORE_TRIGGERED_BY` | `false` | grava quem disparou (dado pessoal) |
| `BOTAPP_CI_ALLOW_INSECURE` | `false` | permite `http://` na base_url |
| `BOTAPP_CI_TIMEOUT_SECONDS` | `30` | timeout por chamada |

## 10. Fases

| fase | entrega | pronto quando |
|---|---|---|
| **1** | modelos + migração 0013 + admin + cliente GitLab + `sync_ci_projects` | projetos e agendamentos aparecem no admin, com token via env |
| **2** | `sync_ci_pipelines` + `run_ci_scheduler` + telas `/ci/` e `/ci/projects/` | pipeline novo aparece no painel sem intervenção |
| **3** | jobs + log sob demanda + `pipeline_failed` | falha de pipeline gera alerta e o log abre pelo painel |
| **4** | `scan_logs` + `pipeline_masked_error` + `schedule_without_run` | verde-que-mente e agendamento morto viram alerta |
| **5** | vínculo com `Bot` + visão unificada + scoping | "rodou no CI e não instrumentou" fica visível |

Cada fase é publicável sozinha. A 1 e a 2 já entregam o inventário e o
acompanhamento; a 4 é a que resolve a classe de problema mais difícil de achar
por outros meios.

## 11. Testes

Sem tocar servidor real: um duplo de teste que serve respostas fixas
(`responses`/`httpx mock` ou um `http.server` local) cobrindo paginação,
403 em projeto isolado, log grande (truncamento), e pipeline verde com padrão de
erro. **Nenhum fixture pode conter host, token ou nome de projeto real.**

## 12. Compatibilidade

A feature é aditiva: `Bot`/`Task`/`TaskLog` e o SDK não mudam, e com
`BOTAPP_CI_ENABLED=false` (default) o comportamento do pacote é idêntico ao
atual. A migração só cria tabelas novas — nada é alterado nem removido.
