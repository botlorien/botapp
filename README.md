# botapp

[![PyPI](https://img.shields.io/pypi/v/botapp.svg)](https://pypi.org/project/botapp/)
[![Python](https://img.shields.io/pypi/pyversions/botapp.svg)](https://pypi.org/project/botapp/)
[![Django](https://img.shields.io/badge/django-%3E%3D3.2-092E20.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**botapp** é um SDK + dashboard Django para observabilidade de automações RPA. Ele instrumenta seus bots com um único decorator, registra cada execução (sucesso, falha, duração, ambiente), expõe um painel web para acompanhamento e dispara alertas (Slack, Discord, e-mail) quando algo foge do esperado.

---

## Sumário

- [Visão geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Arquitetura — modos de uso](#arquitetura--modos-de-uso)
- [Instalação](#instalação)
- [Início rápido](#início-rápido)
- [Modelo de dados](#modelo-de-dados)
- [SDK — instrumentando bots](#sdk--instrumentando-bots)
- [Dashboard web](#dashboard-web)
- [Sistema de alertas](#sistema-de-alertas)
- [API REST](#api-rest)
- [Comandos de gerência](#comandos-de-gerência)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Deploy em produção](#deploy-em-produção)
- [Troubleshooting](#troubleshooting)
- [Desenvolvimento local](#desenvolvimento-local)
- [Licença](#licença)

---

## Visão geral

Quando você mantém uma frota de bots RPA, a dor de cabeça não é escrever o bot — é saber quando ele parou de rodar, quando passou a falhar demais ou quando está mais lento do que deveria. O `botapp` resolve isso com três camadas acopladas:

1. **SDK** (`from botapp import BotApp`) — um decorator `@app.task` que envolve suas funções e grava cada execução no banco automaticamente.
2. **Dashboard web** — painel administrativo Django com listagens, detalhes de logs, exploração filtrada, exportação CSV/PDF e gestão de alertas.
3. **Motor de alertas** — um scheduler que varre periodicamente o banco em busca de anomalias (`silent_bot`, `error_spike`, `heartbeat_lost`, `duration_regression`) e dispara notificações em Slack, Discord e e-mail.

Todos os três podem ser usados em conjunto ou separadamente.

---

## Funcionalidades

### Observabilidade
- Decorator único para instrumentar tarefas (`@app.task`), com captura automática de:
  - `host_name`, `host_ip`, `user_login`, `pid`, `bot_dir`
  - `os_platform`, `python_version`, `env` (dev/staging/prod)
  - `start_time`, `end_time`, `duration`, `status`, `exception_type`, `error_message`, `trigger_source`.
- Denormalização `Bot.last_execution_at` / `Bot.last_status` via `post_save` signal para listagens rápidas.
- Função `reconcile_bot_last_execution()` para self-heal quando SDKs antigos escrevem logs sem disparar signals.

### Dashboard
- Lista de bots com status, última execução, contadores, filtros por departamento/status.
- Detalhe do bot com histórico paginado de execuções, gráficos de taxa de erro e duração.
- Página **Dashboard global** com contadores agregados (bots ativos, silenciosos, alertas críticos).
- **Explore** — filtros combinados em TaskLog com exportação CSV.
- **Manutenção** — ações de limpeza de órfãos e configuração em massa de thresholds por bot.
- Tema responsivo, CSP opcional, rate limiting em rotas sensíveis.

### Alertas
- 4 regras de detecção prontas, todas com severidade graduada (`low`, `medium`, `high`, `critical`):
  - **silent_bot** — bot ativo sem execução há mais de N horas/minutos.
  - **error_spike** — pico de falhas em janela recente.
  - **heartbeat_lost** — log com `status='started'` que nunca fechou.
  - **duration_regression** — duração média recente acima do SLA da task.
- Idempotência: não cria alerta duplicado se já existir um ativo do mesmo tipo para o mesmo bot.
- Dispatcher multi-canal com fallback tolerante (Slack, Discord, e-mail).
- Ações de `acknowledge` e `resolve` via UI ou REST.
- Override de threshold por bot (`silence_threshold_hours`, `silence_threshold_minutes`).

### API REST
- DRF com `ViewSets` para `Bot`, `Task`, `TaskLog`.
- Autenticação `SessionAuthentication` + `BasicAuthentication`.
- Permissão padrão: `IsAuthenticated`.
- Rate limiting em endpoints sensíveis via `django-ratelimit`.

### Operacional
- Comandos de gerência para setup, scheduler, limpeza de órfãos e reconciliação.
- Thread in-process opcional para dev (`BOTAPP_ALERT_SCHEDULER_ENABLED`).
- Comando dedicado para produção multi-worker: `botapp run_alert_scheduler`.

---

## Arquitetura — modos de uso

O `botapp` pode ser consumido de duas formas, detectadas automaticamente em `botapp/__init__.py`:

### Modo standalone
Quando `DJANGO_SETTINGS_MODULE` não está definido, o pacote usa seu próprio `botapp.settings`. É assim que o dashboard é servido como serviço autônomo.

```python
from botapp import BotApp  # resolve para botapp.core.BotApp
app = BotApp('meu_banco')
```

- Grava direto no Postgres usando os modelos Django.
- Ideal para bots que rodam no mesmo host/rede do banco.

### Modo plugin (REST client)
Quando o SDK é importado dentro de **outro** projeto Django (`DJANGO_SETTINGS_MODULE` definido e `ROOT_URLCONF` diferente de `botapp.urls`), `BotApp` é substituído por `BotAppRestful`, que fala com um dashboard remoto via HTTP.

```python
# Em outro projeto Django, com BOTAPP_API_URL apontando para o dashboard remoto
from botapp import BotApp  # resolve para botapp.core_restful.BotAppRestful
app = BotApp()
```

- Não exige acesso direto ao banco.
- Perfeito para bots embarcados em aplicações maiores ou em redes segregadas.
- Requer `BOTAPP_API_URL`, `BOTAPP_API_USUARIO`, `BOTAPP_API_SENHA`.

---

## Instalação

Requisitos: Python 3.8+, Django 3.2+, Postgres 12+ (SQLite funciona para testes).

```bash
pip install botapp
```

Dependências instaladas automaticamente: `Django`, `psycopg2-binary`, `djangorestframework`, `django-admin-rangefilter`, `django-ratelimit`, `whitenoise`, `python-dotenv`, `openpyxl`, `xhtml2pdf`, `requests`.

---

## Início rápido

### 1. Configure o ambiente

Crie um `.env` na raiz do projeto:

```ini
BOTAPP_DEBUG=True
BOTAPP_SECRET_KEY=troque-em-producao
BOTAPP_ALLOWED_HOSTS=*

# Postgres
PG_BOTAPP_SCHEMA=botapp_schema
PG_BOTAPP_DBNAME=botapp
PG_BOTAPP_USER=botapp
PG_BOTAPP_PASSWORD=senha
PG_BOTAPP_HOST=localhost
PG_BOTAPP_PORT=5432

# Superusuário inicial (criado pelo comando setup)
BOTAPP_SUPERUSER_USERNAME=admin
BOTAPP_SUPERUSER_EMAIL=admin@example.com
BOTAPP_SUPERUSER_PASSWORD=troque-em-producao
```

### 2. Inicialize o banco

```bash
botapp setup      # cria schema + roda migrations + cria superusuário
```

### 3. Suba o dashboard

```bash
botapp runserver 0.0.0.0:8000
```

Acesse `http://localhost:8000/`.

### 4. Instrumente um bot

```python
from botapp import BotApp

app = BotApp('botapp')  # mesmo PG_BOTAPP_DBNAME
app.set_bot(
    bot_name='relatorio_diario',
    bot_description='Consolida vendas do dia',
    bot_version='1.0.0',
    bot_department='Financeiro',
)

@app.task
def gerar_relatorio():
    """Gera e envia o relatório diário."""
    # seu código aqui
    return 'ok'

gerar_relatorio()  # será registrada como TaskLog automaticamente
```

---

## Modelo de dados

```
Bot
 ├── name, description, version, department
 ├── is_active
 ├── last_execution_at (denorm)      ← atualizado pelo signal em TaskLog
 ├── last_status (denorm)
 ├── silence_threshold_hours/minutes ← override por bot do limiar de silent_bot
 └── tasks (1:N)

Task
 ├── bot (FK)
 ├── name (__name__ da função decorada)
 ├── description (docstring)
 ├── expected_duration_seconds      ← SLA usado pelo detector de regressão
 └── logs (1:N)

TaskLog
 ├── task (FK)
 ├── status                         ← started | completed | failed
 ├── start_time / end_time / duration
 ├── result_data (JSON)             ← retorno da função serializado
 ├── error_message / exception_type ← traceback do erro, se houver
 ├── host_ip, host_name, pid, user_login, os_platform, python_version
 ├── bot_dir, env, trigger_source, manual_trigger
 └── indexes: -start_time, task+-start_time, status+-start_time, env+-start_time

Alert
 ├── type        ← silent_bot | error_spike | heartbeat_lost | duration_regression
 ├── severity    ← low | medium | high | critical
 ├── bot (FK, nullable)             ← null = alerta global
 ├── message, payload (JSON)
 ├── created_at / updated_at
 ├── acked_at, acked_by (FK User)   ← reconhecimento manual
 ├── resolved_at, resolved_by       ← resolução manual
 └── notified_at                    ← última vez que o dispatcher enviou
```

Migrations relevantes:
- `0008_indexes_performance` — índices de performance em TaskLog.
- `0009_bot_last_execution_denorm` — campos denormalizados em Bot.
- `0010_alerts` — tabela `Alert`.
- `0011_task_expected_duration_seconds` — SLA por task.
- `0012_bot_silence_threshold_minutes` — granularidade fina por bot.

---

## SDK — instrumentando bots

### `BotApp` (standalone)

```python
from botapp import BotApp

app = BotApp(db_name='botapp')
app.set_bot(
    bot_name='meu_bot',           # normalizado: só alfanuméricos, capitalize
    bot_description='O que faz',
    bot_version='1.2.3',
    bot_department='TI',
)

@app.task
def minha_tarefa(arg1, arg2):
    """Docstring vira a description da Task."""
    return {'ok': True}
```

Comportamento do decorator:
1. Se o bot estiver `is_active=False`, a execução é bloqueada com exceção.
2. Cria/recupera a `Task` pelo `func.__name__` e atualiza a description se a docstring mudou.
3. Cria `TaskLog(status='started')` com snapshot do ambiente.
4. Executa a função. Em caso de exceção, grava `exception_type` + `error_message` e **re-lança**.
5. No `finally`, seta `end_time` e o status final.

### `BotAppRestful` (modo plugin)

```python
# Em outro projeto Django
from botapp import BotApp  # resolve para BotAppRestful se detectar host Django
app = BotApp()                         # usa BOTAPP_API_URL do env
app.set_bot('meu_bot', 'desc', '1.0', 'TI')

@app.task
def tarefa():
    ...
```

O fluxo é o mesmo, mas todas as operações batem na API REST do dashboard remoto via `requests`. Credenciais vêm de `BOTAPP_API_USUARIO` / `BOTAPP_API_SENHA` (HTTP Basic).

---

## Dashboard web

Rotas principais (prefixadas por `/` quando em modo standalone):

| Rota                                          | Descrição                                                  |
|-----------------------------------------------|------------------------------------------------------------|
| `/bots/`                                      | Lista de bots com filtros.                                 |
| `/bots/<id>/`                                 | Detalhe do bot: execuções, métricas, gráficos.             |
| `/bot/<id>/toggle-status/`                    | Liga/desliga bot (POST).                                   |
| `/log/<id>/`                                  | Detalhe completo de um `TaskLog`.                          |
| `/dashboard/`                                 | Painel agregado: bots ativos, silenciosos, alertas.        |
| `/alerts/`                                    | Lista de alertas (filtros: status, severity, type, bot).   |
| `/alerts/<id>/ack/`                           | POST — ack um alerta.                                      |
| `/alerts/<id>/resolve/`                       | POST — resolve um alerta.                                  |
| `/alerts/unread-count/`                       | JSON para badge do menu (polling leve).                    |
| `/maintenance/cleanup-orphans/`               | UI para acionar `cleanup_orphans` via HTTP.                |
| `/maintenance/silence-thresholds/`            | Edição em massa de thresholds de silent_bot.               |
| `/bots/bulk-silence-threshold/`               | Ação em massa dos thresholds.                              |
| `/explore/`                                   | Filtros combinados em TaskLog.                             |
| `/explore/export.csv`                         | Exporta o resultado filtrado como CSV.                     |
| `/admin/`                                     | Django admin.                                              |
| `/api/`                                       | API REST (ver seção [API REST](#api-rest)).                |
| `/accounts/login/` · `/accounts/logout/`      | Autenticação.                                              |
| `/accounts/password_reset/…`                  | Fluxo completo de reset por e-mail.                        |

---

## Sistema de alertas

### Regras

| Tipo                  | Dispara quando                                                           | Severidade calculada em função de              |
|-----------------------|--------------------------------------------------------------------------|------------------------------------------------|
| `silent_bot`          | Bot `is_active` sem execução há mais de N horas (override por bot ok).   | `horas_silencio / threshold`                   |
| `error_spike`         | ≥ X falhas em janela deslizante de M minutos.                            | `falhas / threshold`                           |
| `heartbeat_lost`      | Log com `status='started'` mais antigo que N horas.                      | Severidade fixa por idade                      |
| `duration_regression` | Média das últimas N execuções acima de `expected_duration_seconds × k`.  | `duração_média / expected`                     |

### Dispatcher (`notifiers.py`)

Ao criar um alerta, `check_alerts` chama `dispatch_alert(alert)` que envia para todos os canais configurados. Cada canal é **opt-in**: se a env var correspondente não estiver definida, o canal é silenciosamente ignorado. Uma falha em um canal não bloqueia os outros.

- **Slack**: webhook com attachment colorido por severidade.
- **Discord**: embed com cor hex equivalente.
- **E-mail**: usa `settings.EMAIL_*` (SMTP do Django) com lista de destinatários em `BOTAPP_ALERT_EMAIL_RECIPIENTS`.

Se qualquer canal teve sucesso, `alert.notified_at` é atualizado — assim, executar `check_alerts` em intervalo curto não re-dispara notificações a cada rodada.

### Como rodar o detector

**Desenvolvimento** (thread in-process, single worker):

```ini
BOTAPP_ALERT_SCHEDULER_ENABLED=true
BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS=60
```

Ao subir o Django, o `AppConfig.ready()` inicia uma thread daemon que loopa `check_alerts` a cada intervalo. **Não use em produção com múltiplos workers** — N workers × N schedulers gera concorrência e alertas duplicados.

**Produção** (processo dedicado):

```bash
botapp run_alert_scheduler --interval 60
```

Ou em container:

```yaml
services:
  botapp_scheduler:
    image: meu-registry/botapp
    environment:
      BOTAPP_ROLE: scheduler
    command: botapp run_alert_scheduler
```

Flags úteis:
- `--interval N` — sobrescreve `BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS`.
- `--once` — roda uma vez e sai (útil para cron externo).
- `check_alerts --dry-run` — só loga o que faria.
- `check_alerts --no-notify` — cria alertas mas não envia webhooks.

---

## API REST

Base: `/api/`  ·  Autenticação: `Session` ou `Basic`  ·  Permissão: `IsAuthenticated`.

| Método · Rota                  | Descrição                                    |
|-------------------------------|----------------------------------------------|
| `GET    /api/bots/`           | Lista bots (parametros: `search`).           |
| `POST   /api/bots/`           | Cria bot.                                    |
| `GET    /api/bots/{id}/`      | Detalhe.                                     |
| `PATCH  /api/bots/{id}/`      | Atualização parcial.                         |
| `DELETE /api/bots/{id}/`      | Remove.                                      |
| `GET    /api/tasks/`          | Lista tasks (`?bot=<id>&name=<str>`).        |
| `POST   /api/tasks/`          | Cria task.                                   |
| `GET    /api/tasklog/`        | Lista logs.                                  |
| `POST   /api/tasklog/`        | Cria log (usado pelo `BotAppRestful`).       |
| `PATCH  /api/tasklog/{id}/`   | Atualiza log (status, end_time, duration…).  |

Exemplo:

```bash
curl -u admin:senha http://localhost:8000/api/bots/?search=relatorio
```

---

## Comandos de gerência

Disponíveis via entry point `botapp` (equivalente a `python manage.py`):

| Comando                                   | Uso                                                              |
|-------------------------------------------|------------------------------------------------------------------|
| `botapp setup`                            | Cria schema + roda migrations + cria superusuário.               |
| `botapp migrate [--noinput]`              | Aplica migrations.                                               |
| `botapp collectstatic [--noinput]`        | Coleta estáticos (whitenoise em produção).                       |
| `botapp runserver [host:port]`            | Servidor dev.                                                    |
| `botapp check_alerts [--dry-run] [--no-notify]` | Roda o motor de alertas uma vez.                           |
| `botapp run_alert_scheduler [--interval N] [--once]` | Loop blocante do motor (para processo dedicado).      |
| `botapp cleanup_orphans [--threshold-hours N] [--bot-id ID] [--dry-run] [--batch-size N] [--sleep-ms N]` | Fecha logs travados. |
| `botapp reconcile_bot_denorm`             | Reconcilia `Bot.last_execution_at` com o TaskLog real mais recente. |

---

## Variáveis de ambiente

### Essenciais

| Variável                   | Default                            | Descrição                                                |
|----------------------------|-------------------------------------|----------------------------------------------------------|
| `DJANGO_SETTINGS_MODULE`   | `botapp.settings` (standalone)      | Aponta para seu settings em modo plugin.                 |
| `BOTAPP_DEBUG`             | `False`                             | Modo debug do Django.                                    |
| `BOTAPP_SECRET_KEY`        | _obrigatório em prod_               | Secret key. Default de dev não é aceito com `DEBUG=False`. |
| `BOTAPP_ALLOWED_HOSTS`     | `*`                                 | Lista separada por vírgula.                              |
| `BOTAPP_CSRF_TRUSTED_ORIGINS` | `*` (quando `DEBUG=False`)       | Lista separada por vírgula.                              |
| `BOTAPP_PORT_ADMIN`        | `8000`                              | Porta usada por `app.open_admin()`.                      |
| `BOTAPP_LANGUAGE_CODE`     | `pt-br`                             |                                                          |
| `BOTAPP_TIME_ZONE`         | `America/Cuiaba`                    | Fuso padrão.                                             |
| `BOTAPP_USE_I18N`          | `True`                              |                                                          |
| `BOTAPP_USE_TZ`            | `True`                              | Mantenha `True` para datetimes aware (exigido pelos notifiers). |
| `BOTAPP_DEPLOY_ENV`        | `dev`                               | Gravado em `TaskLog.env`.                                |
| `BOTAPP_LOGGING_LEVEL`     | `INFO`                              | Nível do logger `botapp`.                                |
| `BOTAPP_DJANGO_LOG_LEVEL`  | `WARNING`                           | Nível do logger `django`.                                |

### Banco de dados (Postgres)

| Variável                 | Descrição                                           |
|--------------------------|-----------------------------------------------------|
| `BOTAPP_DATABASES`       | (opcional) JSON com o dict `DATABASES` completo. Sobrescreve as demais. |
| `PG_BOTAPP_SCHEMA`       | Schema das tabelas (default `botapp_schema`).       |
| `PG_BOTAPP_DBNAME`       | Nome do banco.                                       |
| `PG_BOTAPP_USER`         | Usuário.                                             |
| `PG_BOTAPP_PASSWORD`     | Senha.                                               |
| `PG_BOTAPP_HOST`         | Host.                                                |
| `PG_BOTAPP_PORT`         | Porta (default 5432).                                |

### Superusuário inicial (usado por `botapp setup`)

| Variável                      | Default                   |
|-------------------------------|----------------------------|
| `BOTAPP_SUPERUSER_USERNAME`   | `admin`                   |
| `BOTAPP_SUPERUSER_EMAIL`      | `admin@example.com`       |
| `BOTAPP_SUPERUSER_PASSWORD`   | `admin123` (proibido em prod) |

### Cache / Redis

| Variável             | Default                           |
|----------------------|-----------------------------------|
| `BOTAPP_CACHES`      | JSON com o dict `CACHES`. Se ausente em prod, usa Redis.  |
| `BOTAPP_REDIS_URL`   | `redis://botapp_redis:6379/1`     |

### E-mail (SMTP)

| Variável                      | Default                       |
|-------------------------------|-------------------------------|
| `BOTAPP_EMAIL_HOST`           | —                             |
| `BOTAPP_EMAIL_PORT`           | `587`                         |
| `BOTAPP_EMAIL_USER`           | —                             |
| `BOTAPP_EMAIL_PASSWORD`       | —                             |
| `BOTAPP_EMAIL_USE_TLS`        | `True`                        |
| `BOTAPP_DEFAULT_FROM_EMAIL`   | `BOTAPP_EMAIL_USER`           |

### Modo plugin (REST client)

| Variável               | Default  | Descrição                                         |
|------------------------|----------|---------------------------------------------------|
| `BOTAPP_API_URL`       | —        | URL do dashboard remoto. Obrigatório no modo plugin. |
| `BOTAPP_API_USUARIO`   | —        | HTTP Basic user.                                   |
| `BOTAPP_API_SENHA`     | —        | HTTP Basic password.                               |
| `BOTAPP_API_TIMEOUT`   | `10`     | Timeout (s) das chamadas HTTP.                     |

### Scheduler / alertas

| Variável                                     | Default                                       |
|----------------------------------------------|-----------------------------------------------|
| `BOTAPP_ALERT_SCHEDULER_ENABLED`             | `false` (não inicia thread in-process)         |
| `BOTAPP_ALERT_SCHEDULER_INTERVAL_SECONDS`    | `60`                                          |
| `BOTAPP_SILENT_BOT_THRESHOLD_HOURS`          | `24`                                          |
| `BOTAPP_ERROR_SPIKE_WINDOW_MINUTES`          | `60`                                          |
| `BOTAPP_ERROR_SPIKE_THRESHOLD`               | `5`                                           |
| `BOTAPP_HEARTBEAT_LOST_THRESHOLD_HOURS`      | `6`                                           |
| `BOTAPP_DURATION_REGRESSION_MULTIPLIER`      | `1.5`                                         |
| `BOTAPP_DURATION_REGRESSION_WINDOW`          | `20` (últimas N execuções)                     |

### Canais de notificação

| Variável                           | Default | Efeito                                          |
|------------------------------------|---------|-------------------------------------------------|
| `BOTAPP_SLACK_WEBHOOK_URL`         | —       | Se definida, envia para Slack.                  |
| `BOTAPP_DISCORD_WEBHOOK_URL`       | —       | Se definida, envia para Discord.                |
| `BOTAPP_ALERT_EMAIL_RECIPIENTS`    | —       | Lista separada por vírgula. Se vazia, não envia. |
| `BOTAPP_DASHBOARD_URL`             | —       | Base usada para gerar link nas notificações.    |
| `BOTAPP_NOTIFIER_TIMEOUT`          | `5`     | Timeout (s) das chamadas aos webhooks.          |

### Limpeza de órfãos

| Variável                            | Default |
|-------------------------------------|---------|
| `BOTAPP_ORPHAN_THRESHOLD_HOURS`     | `24`    |
| `BOTAPP_ORPHAN_BATCH_SIZE`          | `500`   |
| `BOTAPP_ORPHAN_SLEEP_MS`            | `100`   |
| `BOTAPP_ORPHAN_HTTP_MAX`            | `5000`  |

### Export

| Variável                  | Default | Descrição                                      |
|---------------------------|---------|------------------------------------------------|
| `BOTAPP_CSV_MAX_ROWS`     | `0`     | `0` = ilimitado. Teto opcional para `/explore/export.csv`. |

---

## Deploy em produção

Topologia recomendada:

```
┌──────────────┐   ┌────────────────────┐   ┌─────────────────────┐
│  Bots (SDK)  │──▶│  web (gunicorn)    │──▶│  Postgres + Redis   │
└──────────────┘   │  BOTAPP_ROLE=web   │   └─────────────────────┘
                   │  N workers         │
                   └────────────────────┘
                           │
                   ┌────────────────────┐
                   │  scheduler         │  (um único processo)
                   │  BOTAPP_ROLE=      │
                   │     scheduler      │
                   └────────────────────┘
```

Pontos importantes:

1. **Nunca** deixe `BOTAPP_ALERT_SCHEDULER_ENABLED=true` no container `web` com múltiplos workers — use um container `scheduler` dedicado.
2. Rode `botapp migrate` **antes** do primeiro start (ou no entrypoint do serviço web).
3. Configure `BOTAPP_SECRET_KEY`, `BOTAPP_ALLOWED_HOSTS`, `BOTAPP_CSRF_TRUSTED_ORIGINS` explicitamente.
4. HTTPS reverse proxy na frente do gunicorn; o settings já ativa `SECURE_SSL_REDIRECT`, HSTS e cookies seguros quando `DEBUG=False`.
5. `BOTAPP_DASHBOARD_URL` deve apontar para a URL pública do dashboard — usado nos links das notificações.

Exemplo de `docker-compose` mínimo:

```yaml
services:
  web:
    image: botapp:latest
    environment:
      BOTAPP_ROLE: web
      BOTAPP_ALERT_SCHEDULER_ENABLED: "false"
    env_file: .env.prod
    ports: ["8000:8000"]

  scheduler:
    image: botapp:latest
    environment:
      BOTAPP_ROLE: scheduler
      BOTAPP_ALERT_SCHEDULER_ENABLED: "true"
    env_file: .env.prod
    command: botapp run_alert_scheduler
    depends_on: [web]

  redis:
    image: redis:alpine
```

---

## Troubleshooting

**Alertas não estão sendo criados.**
Verifique nessa ordem: (1) a migration `0010_alerts` rodou (`\dt botapp_alert` no psql); (2) o scheduler está rodando (`botapp run_alert_scheduler` em container dedicado **ou** `BOTAPP_ALERT_SCHEDULER_ENABLED=true` em dev); (3) existem bots com `is_active=True` e últimos logs fora do threshold. Rode `botapp check_alerts --dry-run` para ver o que seria criado sem tocar no banco.

**Alertas criados mas sem notificação.**
Nenhuma das envs de canal foi definida — o dispatcher pula canais sem configuração. Defina pelo menos uma entre `BOTAPP_SLACK_WEBHOOK_URL`, `BOTAPP_DISCORD_WEBHOOK_URL`, `BOTAPP_ALERT_EMAIL_RECIPIENTS`. Verifique o log do scheduler por `notifier.slack: falha` / `notifier.discord: falha` / `notifier.email: falha`.

**`Bot.last_execution_at` desatualizado.**
SDK antigo (sem o signal `post_save`) está escrevendo TaskLog direto no banco. Rode `botapp reconcile_bot_denorm` manualmente ou aguarde o `check_alerts` (ele chama a reconciliação a cada rodada).

**Muitos alertas `heartbeat_lost`.**
Crashes deixaram logs em `status='started'`. Rode `botapp cleanup_orphans --threshold-hours 24` para fechá-los retroativamente como `failed/orphan_heartbeat`.

**`ProgrammingError: relation "botapp_alert" does not exist`.**
As migrations não rodaram no ambiente. Execute `botapp migrate --noinput`.

**`Unknown command: 'check_alerts'`.**
Você está em uma versão < 0.3.1, que foi publicada sem o diretório `management/`. Atualize para `0.3.1+`.

---

## Desenvolvimento local

```bash
git clone https://github.com/botlorien/botapp
cd botapp
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install build twine

# Configure .env como na seção "Início rápido"
botapp setup
botapp runserver
```

Para testar o SDK contra o banco local, use `example.py` como referência.

### Publicando uma nova versão

```bash
python setup.py sdist bdist_wheel
twine upload dist/*
```

Antes de publicar, verifique que `find_packages()` detecta todos os subpacotes (em particular `botapp.management` e `botapp.management.commands`, que precisam de `__init__.py`):

```bash
python -c "from setuptools import find_packages; print(find_packages())"
```

---

## Licença

MIT — ver [LICENSE](LICENSE).
