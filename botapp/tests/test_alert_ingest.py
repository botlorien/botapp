"""Testes do endpoint de ingest de alertas (POST /api/alerts/ingest/).

Primeiro teste do pacote a autenticar a API por Token DRF (os demais usam
sessão via force_login). O endpoint é máquina-a-máquina, então o Token é o
caminho real de produção (Grafana → botapp).
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token

from botapp.models import Alert, Bot


class AlertIngestTests(TestCase):
    URL = '/api/alerts/ingest/'

    def setUp(self):
        self.user = get_user_model().objects.create_user('grafana-ingest', password='x')
        self.token = Token.objects.create(user=self.user)
        self.auth = f'Token {self.token.key}'

    def _post(self, body, auth=None):
        return self.client.post(
            self.URL,
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=self.auth if auth is None else auth,
        )

    # ── auth ────────────────────────────────────────────────────────────────
    def test_sem_token_nega(self):
        r = self.client.post(
            self.URL, data=json.dumps({'type': 'x', 'message': 'y'}),
            content_type='application/json',
        )
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(Alert.objects.count(), 0)

    def test_token_invalido_nega(self):
        r = self._post({'type': 'x', 'message': 'y'}, auth='Token nao-existe')
        self.assertIn(r.status_code, (401, 403))

    # ── criação ───────────────────────────────────────────────────────────────
    def test_cria_alerta_firing(self):
        r = self._post({
            'type': 'host_disk',
            'severity': 'critical',
            'message': 'Disco cheio em docker01 (92%)',
            'fingerprint': 'abc123',
            'payload': {'host': 'docker01', 'usado': 92},
        })
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['created'], 1)
        a = Alert.objects.get()
        self.assertEqual(a.type, 'host_disk')
        self.assertEqual(a.severity, Alert.Severity.CRITICAL)
        self.assertIsNone(a.resolved_at)
        self.assertEqual(a.payload['fingerprint'], 'abc123')
        self.assertEqual(a.payload['host'], 'docker01')

    def test_severity_default_medium(self):
        self._post({'type': 't', 'message': 'm'})
        self.assertEqual(Alert.objects.get().severity, Alert.Severity.MEDIUM)

    def test_associa_bot_por_nome_quando_existe(self):
        bot = Bot.objects.create(name='bot_x')
        self._post({'type': 't', 'message': 'm', 'bot_name': 'bot_x'})
        self.assertEqual(Alert.objects.get().bot_id, bot.id)

    def test_bot_inexistente_vira_alerta_global(self):
        self._post({'type': 't', 'message': 'm', 'bot_name': 'nao-existe'})
        self.assertIsNone(Alert.objects.get().bot_id)

    # ── deduplicação ──────────────────────────────────────────────────────────
    def test_dedup_por_fingerprint(self):
        body = {'type': 'host_disk', 'message': 'd1', 'fingerprint': 'fp1'}
        self.assertEqual(self._post(body).json()['created'], 1)
        r2 = self._post(body)
        self.assertEqual(r2.json()['created'], 0)
        self.assertEqual(r2.json()['deduped'], 1)
        self.assertEqual(Alert.objects.count(), 1)

    def test_dedup_por_type_message_sem_fingerprint(self):
        body = {'type': 'host_cpu', 'message': 'cpu alta docker02'}
        self._post(body)
        self._post(body)
        self.assertEqual(Alert.objects.count(), 1)

    def test_fingerprint_diferente_cria_outro(self):
        self._post({'type': 't', 'message': 'm', 'fingerprint': 'a'})
        self._post({'type': 't', 'message': 'm', 'fingerprint': 'b'})
        self.assertEqual(Alert.objects.count(), 2)

    def test_reabre_apos_resolvido(self):
        body = {'type': 't', 'message': 'm', 'fingerprint': 'fp'}
        self._post(body)
        self._post({**body, 'status': 'resolved'})
        # com o anterior resolvido, um novo firing deve criar de novo
        self._post(body)
        self.assertEqual(Alert.objects.filter(resolved_at__isnull=True).count(), 1)
        self.assertEqual(Alert.objects.count(), 2)

    # ── resolução ─────────────────────────────────────────────────────────────
    def test_resolved_fecha_ativo(self):
        body = {'type': 't', 'message': 'm', 'fingerprint': 'fp'}
        self._post(body)
        r = self._post({**body, 'status': 'resolved'})
        self.assertEqual(r.json()['resolved'], 1)
        self.assertIsNotNone(Alert.objects.get().resolved_at)

    def test_resolved_sem_alerta_ativo_nao_falha(self):
        r = self._post({'type': 't', 'message': 'm', 'status': 'resolved'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['resolved'], 0)

    # ── lote e validação ──────────────────────────────────────────────────────
    def test_lote_alerts_array(self):
        r = self._post({'alerts': [
            {'type': 'a', 'message': 'm1', 'fingerprint': '1'},
            {'type': 'b', 'message': 'm2', 'fingerprint': '2'},
        ]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['created'], 2)
        self.assertEqual(Alert.objects.count(), 2)

    def test_item_invalido_no_lote_reporta_207(self):
        r = self._post({'alerts': [
            {'type': 'ok', 'message': 'm'},
            {'type': 'faltou message'},
        ]})
        self.assertEqual(r.status_code, 207)
        self.assertEqual(r.json()['created'], 1)
        self.assertTrue(r.json()['errors'])
        self.assertEqual(Alert.objects.count(), 1)

    def test_type_ausente_400(self):
        r = self._post({'message': 'm'})
        self.assertEqual(r.status_code, 207)
        self.assertEqual(Alert.objects.count(), 0)

    def test_severity_invalida_400(self):
        r = self._post({'type': 't', 'message': 'm', 'severity': 'apocaliptica'})
        self.assertEqual(r.status_code, 207)
        self.assertEqual(Alert.objects.count(), 0)

    def test_payload_nao_objeto_400(self):
        r = self._post({'type': 't', 'message': 'm', 'payload': [1, 2, 3]})
        self.assertEqual(r.status_code, 207)
        self.assertEqual(Alert.objects.count(), 0)
