from django.db import connection

def ensure_schema_exists(schema_name):
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
