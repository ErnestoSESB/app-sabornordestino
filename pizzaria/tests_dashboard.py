from datetime import datetime, timedelta, timezone as utc_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Pedido


class FaturamentoDashboardTests(TestCase):
    """O total do dia não pode sumir quando o pedido é marcado como Pago."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username='dono', password='123456')
        self.client.force_login(self.usuario)

    def _criar_pedido(self, criado_em, status='Em andamento', total='39.00'):
        pedido = Pedido.objects.create(cliente='Cliente Teste', total=total, status=status)
        # criado_em é auto_now_add, então ajustamos direto no banco.
        Pedido.objects.filter(pk=pedido.pk).update(criado_em=criado_em)
        return pedido

    def test_pedido_pago_continua_no_total_de_hoje_a_noite(self):
        # 02:00 UTC = 23:00 do dia anterior no fuso da pizzaria (America/Fortaleza).
        momento = datetime(2026, 9, 24, 2, 0, tzinfo=utc_timezone.utc)
        data_local = momento.astimezone(timezone.get_current_timezone()).date()
        self.assertNotEqual(momento.date(), data_local)  # garante o cenário noturno

        pedido = self._criar_pedido(momento)

        def carregar_dashboard():
            with patch.object(timezone, 'localdate', return_value=data_local), \
                    patch.object(timezone, 'now', return_value=momento):
                return self.client.get(reverse('painel'))

        antes = carregar_dashboard()
        self.assertEqual(antes.status_code, 200)
        self.assertEqual(antes.context['faturamento_hoje'], Decimal('39.00'))
        self.assertEqual(antes.context['pedidos_hoje'], 1)
        self.assertEqual(antes.context['grafico_vendas'][-1]['data'], data_local.strftime('%d/%m'))
        self.assertEqual(antes.context['grafico_vendas'][-1]['valor'], 39.0)

        # Marcar como Pago não pode tirar o valor do montante de hoje.
        self.client.post(
            reverse('pedido_alterar_status', args=[pedido.id]),
            data={'status': 'Pago'},
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, 'Pago')

        depois = carregar_dashboard()
        self.assertEqual(depois.context['faturamento_hoje'], Decimal('39.00'))
        self.assertEqual(depois.context['faturamento_semana'], Decimal('39.00'))
        self.assertEqual(depois.context['faturamento_mes'], Decimal('39.00'))
        self.assertEqual(depois.context['grafico_vendas'][-1]['valor'], 39.0)
        self.assertContains(depois, 'R$ 39.00')

    def test_pedido_de_ontem_nao_entra_no_total_de_hoje(self):
        momento = datetime(2026, 9, 23, 2, 0, tzinfo=utc_timezone.utc)  # 23h de 22/09 local
        data_local = momento.astimezone(timezone.get_current_timezone()).date() + timedelta(days=1)
        self._criar_pedido(momento, status='Pago')

        with patch.object(timezone, 'localdate', return_value=data_local), \
                patch.object(timezone, 'now', return_value=momento + timedelta(days=1)):
            resposta = self.client.get(reverse('painel'))

        self.assertEqual(resposta.context['faturamento_hoje'], 0)
        self.assertEqual(resposta.context['faturamento_semana'], Decimal('39.00'))
        self.assertEqual(resposta.context['faturamento_mes'], Decimal('39.00'))

    def test_dashboard_filtra_faturamento_por_intervalo_de_datas(self):
        self._criar_pedido(datetime(2026, 9, 10, 15, 0, tzinfo=utc_timezone.utc), total='25.00')
        self._criar_pedido(datetime(2026, 9, 20, 15, 0, tzinfo=utc_timezone.utc), total='40.00')

        resposta = self.client.get(reverse('painel'), {
            'data_inicio': '2026-09-15',
            'data_fim': '2026-09-25',
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['faturamento_periodo'], Decimal('40.00'))
        self.assertEqual(resposta.context['pedidos_periodo'], 1)
        self.assertContains(resposta, 'Faturamento no período selecionado')

    def test_dashboard_rejeita_intervalo_invertido(self):
        resposta = self.client.get(reverse('painel'), {
            'data_inicio': '2026-09-25',
            'data_fim': '2026-09-15',
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.context['filtro_data_ativo'])
        self.assertContains(resposta, 'Informe um intervalo de datas válido.')