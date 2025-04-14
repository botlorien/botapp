from setuptools import setup, find_packages

setup(
    name='botapp',
    version='0.1.2',
    packages=find_packages(),
    include_package_data=True,  # Inclui arquivos de dados especificados no MANIFEST.in
    license='MIT',
    description='Pacote Django para gerenciamento de bots e tarefas de RPA',
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    author='Ben-Hur P. B. Santos',
    author_email='botlorien@gmail.com',
    classifiers=[
        'Framework :: Django',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    install_requires=[
        'Django>=3.2',
        'psycopg2-binary>=2.9.10',
        'django-admin-rangefilter',
        'openpyxl',
        'python-dotenv>=1.0.0',
        'xhtml2pdf>=0.2.5',
    ],
    python_requires='>=3.8',
)

# pip install setuptools
# python setup.py sdist
# pip install twine
# twine upload dist/*