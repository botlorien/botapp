"""Reconcilia os alertas de CI já existentes.

Duas coisas que só podem ser feitas olhando o passado:

1. **Completa o payload** dos alertas criados antes de o payload passar a
   carregar os ids internos. Sem eles o painel só consegue oferecer "reconhecer"
   e "resolver" — o operador não chega ao log para entender o que houve.
2. **Resolve o que já foi superado**: alerta de pipeline que falhou às 3h e
   passou às 4h. Alerta obsoleto acumulado esconde o alerta que importa.

Uso:
  python manage.py reconcile_ci_alerts            # aplica
  python manage.py reconcile_ci_alerts --dry-run  # só relata
"""
from django.core.management.base import BaseCommand

from botapp.ci_sync import resolver_alertas_obsoletos
from botapp.models import Alert, CIConnection, CIJob, CIPipeline

TIPOS = [Alert.Type.PIPELINE_FAILED, Alert.Type.PIPELINE_MASKED_ERROR]


class Command(BaseCommand):
    help = 'Completa o payload e resolve alertas de CI já superados.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Relata sem alterar nada.')

    def handle(self, *args, **opts):
        seco = opts['dry_run']

        completados = 0
        for alerta in Alert.objects.filter(type__in=TIPOS):
            payload = dict(alerta.payload or {})
            if payload.get('pipeline_db_id'):
                continue
            projeto_id, externo = payload.get('project_id'), payload.get('pipeline_id')
            if not projeto_id or not externo:
                continue
            pipeline = CIPipeline.objects.filter(project_id=projeto_id,
                                                 external_id=externo).first()
            if not pipeline:
                continue
            payload['pipeline_db_id'] = pipeline.id
            job = (pipeline.jobs.filter(status='failed').first()
                   or pipeline.jobs.exclude(log_excerpt='').first()
                   or pipeline.jobs.first())
            if job:
                payload['job_db_id'] = job.id
            if not seco:
                alerta.payload = payload
                alerta.save(update_fields=['payload'])
            completados += 1

        self.stdout.write(self.style.SUCCESS(
            f'{completados} alerta(s) com payload completado'
            f'{" (simulação)" if seco else ""}'))

        if seco:
            candidatos = 0
            for conexao in CIConnection.objects.all():
                # conta sem alterar: repete a regra do resolvedor
                for alerta in Alert.objects.filter(type__in=TIPOS,
                                                   resolved_at__isnull=True):
                    p = alerta.payload or {}
                    origem = CIPipeline.objects.filter(
                        project_id=p.get('project_id'),
                        external_id=p.get('pipeline_id')).first()
                    if origem and origem.created_at and CIPipeline.objects.filter(
                            project_id=p.get('project_id'), status='success',
                            has_masked_error=False,
                            created_at__gt=origem.created_at).exists():
                        candidatos += 1
            self.stdout.write(self.style.WARNING(
                f'{candidatos} alerta(s) seriam resolvidos (simulação)'))
            return

        resolvidos = sum(resolver_alertas_obsoletos(c)
                         for c in CIConnection.objects.all())
        self.stdout.write(self.style.SUCCESS(
            f'{resolvidos} alerta(s) resolvidos por execução posterior bem-sucedida'))

        abertos = Alert.objects.filter(type__in=TIPOS, resolved_at__isnull=True).count()
        self.stdout.write(f'{abertos} alerta(s) de CI seguem abertos (procedem)')
