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

BOTAPP_DEBUG: Modo de execução do servidor. Default 'True'
BOTAPP_SECRET_KEY: Chave secreta para o projeto django. Default 'chave-super-secreta-para-dev'
BOTAPP_ALLOWED_HOSTS: Lista de hosts permitidos. Default "['*']"
BOTAPP_PORT_ADMIN: Porta para rodar os servidor para os paineis administrativos. Default 8000

BOTAPP_SUPERUSER_USERNAME: Usuario para o superuser. Default 'admin'
BOTAPP_SUPERUSER_EMAIL: Email do superuser. Default 'admin@example.com'
BOTAPP_SUPERUSER_PASSWORD: Senha do superuser. Default 'admin123'

BOTAPP_DATABASES: (Opcional) Dicionario padrão Django de configuração do banco de dados. Default configuração Postgresl 
Eg:
```python
    BOTAPP_DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('PG_BOTAPP_DBNAME'),      # nome do banco
            'USER':  os.environ.get('PG_BOTAPP_USER'),        # seu usuário do Postgres
            'PASSWORD':  os.environ.get('PG_BOTAPP_PASSWORD'),      # sua senha
            'HOST':  os.environ.get('PG_BOTAPP_HOST'),          # ou IP do servidor
            'PORT':  os.environ.get('PG_BOTAPP_PORT'),               # porta padrão do Postgres
            'OPTIONS': {
                'options': f'-c search_path={PG_BOTAPP_SCHEMA}' # Schema do banco de dados Postgres
            }
        }
    }
````

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

BOTAPP_FORCE_URL_PREFIX: Força prefixo de rota. Default 'botapp' para DEBUG=False

BOTAPP_API_URL: Variável para definir a url da api do serviço botapp rodando em outro servidor quando esse pacote for usando dentro de outro projeto django eg. '127.0.0.1:8888/api'

Você pode definir essas variáveis diretamente no ambiente ou utilizando um arquivo `.env` na raiz do projeto.

## 🚀 Uso

Após configurar as variáveis de ambiente, inicie a aplicação com o seguinte comando:

```bash
botapp setup # cria a estrutura no banco de dados, usuario admin para acesso ao dashboard
botapp runserver # Inicia o servidor http para acesso ao dashboard
```

A interface administrativa estará disponível em:

```
http://localhost:8000/admin/
```

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
python example.py
```

Certifique-se de que todas as dependências estejam instaladas e que as variáveis de ambiente estejam corretamente configuradas antes de executar os testes.

## 📄 Licença

Este projeto está licenciado sob a [Licença MIT](LICENSE).

---

Para mais informações, consulte a [documentação oficial](https://github.com/botlorien/botapp).

