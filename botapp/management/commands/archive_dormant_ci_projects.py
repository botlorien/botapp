"""Arquiva no painel os projetos dormentes.

Dormente = monitorado, sem execução há mais de N dias. O alerta desses é
tecnicamente correto e operacionalmente inútil: ninguém vai consertar um
repositório que ninguém usa há meses, e o volume empurra o alerta real para
fora da tela.

Uso:
  python manage.py archive_dormant_ci_projects --days 60 --dry-run
  python manage.py archive_dormant_ci_projects --days 60
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from botapp.ci_sync import fechar_alertas_de_inativos
from botapp.models import CIConnection, CIProject


class Command(BaseCommand):
    help = 'Arquiva no painel os projetos sem execução há mais de N dias.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60,
                            help='Dias sem execução para considerar dormente.')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--incluir-agendados', action='store_true',
                            help='Inclui projetos COM agendamento ativo. Use com '
                                 'cuidado: agendado que não roda é problema, '
                                 'não repositório abandonado.')

    def handle(self, *args, **opts):
        dias, seco = opts['days'], opts['dry_run']
        incluir_agendados = opts['incluir_agendados']
        corte = timezone.now() - timedelta(days=dias)

        # NUNCA arquivar projeto com agendamento ativo. "Sem execução há 30
        # dias" não quer dizer abandonado: infraestrutura estável (proxy,
        # storage, painel) faz deploy sob demanda e fica meses sem rodar. Já um
        # projeto AGENDADO que não roda é um problema de verdade — é o alerta
        # schedule_without_run, e arquivá-lo esconderia justamente o caso que
        # se quer enxergar.
        candidatos = CIProject.objects.filter(
            monitored=True, archived=False, local_archived=False
        ).filter(last_pipeline_at__lt=corte)
        if not incluir_agendados:
            candidatos = candidatos.exclude(schedules__active=True)
        candidatos = candidatos.distinct()
        # projeto sem NENHUMA execução conhecida entra também, desde que já
        # tenha passado por sync (senão arquivaríamos projeto recém-descoberto)
        sem_run = CIProject.objects.filter(
            monitored=True, archived=False, local_archived=False,
            last_pipeline_at__isnull=True
        ).exclude(pipelines_cursor__isnull=True)
        if not incluir_agendados:
            sem_run = sem_run.exclude(schedules__active=True)
        sem_run = sem_run.distinct()

        total = candidatos.count() + sem_run.count()
        self.stdout.write(
            f'{total} projeto(s) dormente(s) há mais de {dias} dias'
            + ('' if incluir_agendados else ' (agendados preservados)'))
        for p in list(candidatos[:20]) + list(sem_run[:10]):
            quando = (p.last_pipeline_at.strftime('%d/%m/%Y')
                      if p.last_pipeline_at else 'nunca')
            self.stdout.write(f'  {p.path[:56]:58} última execução: {quando}')

        if seco:
            self.stdout.write(self.style.WARNING('simulação — nada alterado'))
            return

        agora = timezone.now()
        for qs in (candidatos, sem_run):
            qs.update(local_archived=True, local_archived_at=agora,
                      local_archived_reason=f'dormente há mais de {dias} dias')
        fechados = sum(fechar_alertas_de_inativos(c)
                       for c in CIConnection.objects.all())
        self.stdout.write(self.style.SUCCESS(
            f'{total} projeto(s) arquivados no painel · '
            f'{fechados} alerta(s) fechados'))
