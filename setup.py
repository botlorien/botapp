from setuptools import find_packages, setup

setup(
    name="botapp",
    version="0.4.3",
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
    install_requires=[
        # Faixa ampla: hosts antigos (3.2) continuam funcionando; hosts novos
        # podem rodar 4.2/5.x sem precisar mudar o pacote. Recomendado: >=4.2
        # para fechar CVEs que só tem patch nas séries em suporte.
        "Django>=3.2,<5.3",
        "psycopg2-binary>=2.9.10",
        "django-admin-rangefilter",
        "openpyxl",
        "python-dotenv>=1.0.0",
        "xhtml2pdf>=0.2.17",  # CVE-2024-25885: ReDoS em getcolor (<0.2.17)
        "whitenoise",
        "djangorestframework",
        "requests",
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
