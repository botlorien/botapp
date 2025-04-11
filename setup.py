from setuptools import setup, find_packages

setup(
    name='botapp',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    license='MIT',
    description='Pacote Django para gerenciamento de bots e tarefas de RPA',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Seu Nome',
    author_email='seuemail@exemplo.com',
    classifiers=[
        'Framework :: Django',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    install_requires=[
        'Django>=3.2',
        'botenv>=0.1.0',
        'psycopg2-binary=2.9.10',
        'django-admin-rangefilter',
    ],
    python_requires='>=3.8',
)
