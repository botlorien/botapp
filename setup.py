from setuptools import find_packages, setup

setup(
    name="botapp",
    version="0.6.17",
    packages=find_packages(),
    include_package_data=True,  # Inclui arquivos de dados especificados no MANIFEST.in
    license="MIT",
    description="Pacote Django para gerenciamento de bots e tarefas de RPA",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Ben-Hur P. B. Santos",
    author_email="botlorien@gmail.com",
    classifiers=[
        "Framework :: Django",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    extras_require={
        # só necessário para CIConnection.token_source="db"; o modo recomendado
        # (token em variável de ambiente) não precisa de nada extra
        "ci-db-token": ["cryptography>=42"],
    },
    install_requires=[
        # Piso em 4.2 (LTS): a 3.2 saiu de suporte em abril/2024 e nao recebe
        # mais correcao de seguranca. Um pacote que manipula token de CI nao
        # pode permitir instalacao sobre uma base sem patch.
        "Django>=4.2,<5.3",
        "psycopg2-binary>=2.9.10",
        "django-admin-rangefilter",
        "openpyxl",
        "python-dotenv>=1.0.0",
        "xhtml2pdf>=0.2.17",  # CVE-2024-25885: ReDoS em getcolor (<0.2.17)
        "whitenoise",
        "djangorestframework>=3.15.2",
        # piso por seguranca: <2.31 vaza Proxy-Authorization em redirect
        # (CVE-2023-32681) e <2.32 nao respeita verify=False por sessao
        # (CVE-2024-35195). O cliente de CI manda token em header.
        "requests>=2.32.0",
        "django-ratelimit",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "botapp=botapp.manage:main",
        ],
    },
)

# pip install setuptools
# python setup.py sdist
# pip install twine
# twine upload dist/*
