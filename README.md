# 🧠 botapp

**botapp** é um pacote Python desenvolvido para registrar operações de RPA (Automação de Processos Robóticos) e outras atividades em um banco de dados. Ele fornece uma interface web administrativa para monitoramento e controle das execuções automatizadas.

## 📦 Instalação

Para instalar o `botapp`, utilize o `pip`:

```bash
pip install botapp
```

## ⚙️ Configuração

O `botapp` utiliza variáveis de ambiente para configurar seu comportamento. Abaixo estão as variáveis disponíveis que podem ser definidas pelo usuário:

### 🔐 Variáveis de Ambiente
DJANGO_SETTINGS_MODULE: Caminho do modulo settings. Default 'botapp.settings'

BOTAPP_SECRET_KEY: Chave secreta para o projeto django. Default 'chave-super-secreta-para-dev'
BOTAPP_ALLOWED_HOSTS: Lista de hosts permitidos. Default "['*']"
BOTAPP_PORT_ADMIN: Porta para rodar os servidor para os paineis administrativos. Default 8000

BOTAPP_SUPERUSER_USERNAME: Usuario para o superuser. Default 'admin'
BOTAPP_SUPERUSER_EMAIL: Email do superuser. Default 'admin@example.com'
BOTAPP_SUPERUSER_PASSWORD: Senha do superuser. Default 'admin123'

PG_BOTAPP_SCHEMA: Nome do schema no banco de dados Postgresql para criar as tabelas. Default 'botapp_schema'
PG_BOTAPP_DBNAME: Nome do database do banco de dados Postgresql
PG_BOTAPP_USER: Usuario do banco de dados Postgresql
PG_BOTAPP_PASSWORD: Senha do usuario do banco de dados Postgresql
PG_BOTAPP_HOST: Host do banco de dados Postgresql
PG_BOTAPP_PORT: Porta do banco de dados Postgresql

BOTAPP_EMAIL_HOST: Host do servidor de emails para rotinas de emails do painel administrativo como redefinição de senha.
BOTAPP_EMAIL_PORT: Porta do servidor de email. Default 587
BOTAPP_EMAIL_USER: Usuario do servidor de email
BOTAPP_EMAIL_PASSWORD: Senha do usuario do servidor de email
BOTAPP_EMAIL_USE_TLS: Boolean para uso de TLS. Default 'True'
BOTAPP_DEFAULT_FROM_EMAIL: Nome de exibição dos emails enviados

BOTAPP_DEPLOY_ENV: Nome do ambiente de deploy eg. Desenvolvimento, Homologação, Produção.

Você pode definir essas variáveis diretamente no ambiente ou utilizando um arquivo `.env` na raiz do projeto.

## 🚀 Uso

Após configurar as variáveis de ambiente, inicie a aplicação com o seguinte comando:

```bash
from botapp import BotApp
app = BotApp('<SeuDatabase>') # substitua '<SeuDatabase>' pelo DBNAME do banco de dados
app.open_admin()
```

A interface administrativa estará disponível em:

```
http://0.0.0.0:<BOTAPP_PORT_ADMIN>/admin
```

Substitua  `<BOTAPP_PORT_ADMIN>` pelos valores configurados nas variáveis de ambiente.

## 🖼️ Capturas de Tela

Abaixo estão algumas capturas de tela das páginas do sistema:

### 📊 Dashboard

![Dashboard](<!-- cole o link aqui -->)

### 📝 Registro de Operações

![Registro de Operações](<!-- cole o link aqui -->)

### 👤 Gerenciamento de Usuários

![Gerenciamento de Usuários](<!-- cole o link aqui -->)

> ℹ️ Substitua os espaços reservados pelos URLs reais das imagens hospedadas.

## 🧪 Testes

Para executar os testes da aplicação, utilize:

```bash
python test.py
python test_open_admin.py
```

Certifique-se de que todas as dependências estejam instaladas e que as variáveis de ambiente estejam corretamente configuradas antes de executar os testes.

## 📄 Licença

Este projeto está licenciado sob a [Licença MIT](LICENSE).

---

Para mais informações, consulte a [documentação oficial](https://github.com/botlorien/botapp).

