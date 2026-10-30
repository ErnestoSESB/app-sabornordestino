from decimal import Decimal
from datetime import timedelta
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from .calculadora_preco import calcular_preco_pizza
from .middleware import RateLimitMiddleware
from .models import Bebida, ItemPedido, Pedido, Pizza, TaxaEntrega


class RateLimitIsolatedTestCase(TestCase):
	def setUp(self):
		cache.clear()
		super().setUp()

	def tearDown(self):
		cache.clear()
		super().tearDown()


class RateLimitMiddlewareTests(RateLimitIsolatedTestCase):
	@override_settings(RATE_LIMIT={'WINDOW': 60, 'REQUESTS': 150})
	def test_allows_limit_requests_then_returns_too_many_requests(self):
		middleware = RateLimitMiddleware(lambda request: HttpResponse(status=200))
		request_factory = RequestFactory()

		for _ in range(150):
			response = middleware(request_factory.get('/', REMOTE_ADDR='203.0.113.1'))
			self.assertEqual(response.status_code, 200)

		response = middleware(request_factory.get('/', REMOTE_ADDR='203.0.113.1'))
		self.assertEqual(response.status_code, 429)

	@override_settings(RATE_LIMIT={'WINDOW': 60, 'REQUESTS': 1})
	def test_static_and_media_requests_do_not_consume_the_limit(self):
		middleware = RateLimitMiddleware(lambda request: HttpResponse(status=200))
		request_factory = RequestFactory()

		for path in ('/static/pizzaria/cardapio.css', '/media/pizzas/image.png'):
			response = middleware(request_factory.get(path, REMOTE_ADDR='203.0.113.2'))
			self.assertEqual(response.status_code, 200)

		response = middleware(request_factory.get('/', REMOTE_ADDR='203.0.113.2'))
		self.assertEqual(response.status_code, 200)
		response = middleware(request_factory.get('/', REMOTE_ADDR='203.0.113.2'))
		self.assertEqual(response.status_code, 429)


class PainelPedidosPollingTests(RateLimitIsolatedTestCase):
	def setUp(self):
		super().setUp()
		get_user_model().objects.create_user(username='admin_poll', password='123456')

	def test_historico_lista_parcial_exige_login_e_retorna_so_cards(self):
		self.assertEqual(self.client.get(reverse('historico_pedidos_lista')).status_code, 302)
		antigo = Pedido.objects.create(cliente='Historico Antigo', total='39.00')
		Pedido.objects.create(cliente='Historico Novo', total='39.00')
		Pedido.objects.filter(pk=antigo.pk).update(criado_em=timezone.now() - timedelta(minutes=30))
		self.client.login(username='admin_poll', password='123456')

		response = self.client.get(reverse('historico_pedidos_lista'))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, '<html')
		conteudo = response.content.decode()
		self.assertLess(conteudo.index('Historico Novo'), conteudo.index('Historico Antigo'))

	def test_historico_configura_polling_com_filtro(self):
		self.client.login(username='admin_poll', password='123456')
		response = self.client.get(reverse('historico_pedidos') + '?data=2026-01-01')
		self.assertContains(response, 'hx-trigger="every 5s')
		self.assertContains(response, reverse('historico_pedidos_lista') + '?data=2026-01-01')

	def test_lista_parcial_exige_login(self):
		response = self.client.get(reverse('painel_pedidos_lista'))
		self.assertEqual(response.status_code, 302)

	def test_lista_parcial_retorna_so_os_cards_com_mais_recentes_primeiro(self):
		antigo = Pedido.objects.create(cliente='Cliente Antigo', total='39.00')
		novo = Pedido.objects.create(cliente='Cliente Novo', total='39.00')
		Pedido.objects.filter(pk=antigo.pk).update(criado_em=timezone.now() - timedelta(minutes=30))
		self.client.login(username='admin_poll', password='123456')

		response = self.client.get(reverse('painel_pedidos_lista') + '?filtro=todos')

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, '<html')
		conteudo = response.content.decode()
		self.assertLess(conteudo.index('Cliente Novo'), conteudo.index('Cliente Antigo'))

	def test_pagina_principal_configura_polling_htmx(self):
		self.client.login(username='admin_poll', password='123456')
		response = self.client.get(reverse('painel_pedidos') + '?filtro=todos')
		self.assertContains(response, 'hx-trigger="every 5s')
		self.assertContains(response, reverse('painel_pedidos_lista') + '?filtro=todos')

	@override_settings(RATE_LIMIT={'WINDOW': 60, 'REQUESTS': 1})
	def test_polling_nao_consome_o_rate_limit(self):
		self.client.login(username='admin_poll', password='123456')
		for _ in range(5):
			self.assertEqual(self.client.get(reverse('painel_pedidos_lista')).status_code, 200)


class RateLimitUsuariosLogadosTests(RateLimitIsolatedTestCase):
	@override_settings(RATE_LIMIT={'WINDOW': 60, 'REQUESTS': 3})
	def test_admin_e_garcom_logados_nao_sao_limitados(self):
		User = get_user_model()
		User.objects.create_user(username='admin_rl', password='123456')
		garcom = User.objects.create_user(username='garcom_rl', password='123456')
		garcom.groups.create(name='Garçons')

		for username in ('admin_rl', 'garcom_rl'):
			client = Client()
			client.login(username=username, password='123456')
			for _ in range(10):
				self.assertNotEqual(client.get(reverse('painel_pedidos')).status_code, 429)

	@override_settings(RATE_LIMIT={'WINDOW': 60, 'REQUESTS': 3})
	def test_visitante_anonimo_continua_limitado(self):
		codigos = [Client().get(reverse('cardapio')).status_code for _ in range(5)]
		self.assertEqual(codigos, [200, 200, 200, 429, 429])


class PedidoEdicaoTests(RateLimitIsolatedTestCase):
	def setUp(self):
		super().setUp()
		User = get_user_model()
		self.admin = User.objects.create_user(username='admin_edit', password='123456')
		self.motoqueiro = User.objects.create_user(username='moto_edit', password='123456')
		self.garcom = User.objects.create_user(username='garcom_edit', password='123456')
		self.garcom.groups.create(name='Garçons')
		self.taxa_a = TaxaEntrega.objects.create(nome='Bairro A', taxa='6.00', ativo=True)
		self.taxa_b = TaxaEntrega.objects.create(nome='Bairro B', taxa='8.00', ativo=True)
		self.pizza = Pizza.objects.create(nome='Calabresa Edit', ingredientes='Calabresa', disponivel=True)
		self.coca = Bebida.objects.create(nome='Coca Edit', preco='8.00', disponivel=True)
		self.pedido = Pedido.objects.create(
			usuario=self.garcom, cliente='Cliente Original', telefone='84999990000',
			endereco='Rua A', forma_pagamento='PIX', local_entrega=self.taxa_a,
			taxa_entrega='6.00', subtotal='47.00', total='53.00',
			status='Em preparo', motoqueiro=self.motoqueiro, numero_do_dia=7,
		)
		self.item_pizza = ItemPedido.objects.create(
			pedido=self.pedido, item_tipo='pizza', pizza=self.pizza, quantidade=1, preco_unitario='39.00')
		self.item_bebida = ItemPedido.objects.create(
			pedido=self.pedido, item_tipo='bebida', bebida=self.coca, quantidade=1, preco_unitario='8.00')

	def _dados(self, **extra):
		"""Formulário completo (admin): os itens são refeitos a partir dele."""
		dados = {
			'cliente': 'Cliente Editado', 'telefone': '84988887777', 'endereco': 'Rua B, 10',
			'local_entrega': str(self.taxa_b.id), 'forma_pagamento': 'Dinheiro', 'troco': '100,00',
			'observacao': 'Sem cebola',
			'sabor_1[]': [str(self.pizza.id)], 'num_sabores[]': ['1'], 'tamanho[]': ['G'],
			'quantidade[]': ['2'], 'observacao_item[]': ['Bem assada'],
			'bebida_id[]': [str(self.coca.id)], 'bebida_quantidade[]': ['1'],
		}
		dados.update(extra)
		return dados

	def test_admin_ve_formulario_completo_preenchido(self):
		self.client.login(username='admin_edit', password='123456')
		response = self.client.get(reverse('pedido_editar', args=[self.pedido.id]))
		self.assertTemplateUsed(response, 'pizzaria/pedido_form.html')
		self.assertContains(response, 'value="Cliente Original"')
		self.assertContains(response, 'value="84999990000"')
		self.assertContains(response, 'Rua A</textarea>')
		self.assertContains(response, 'edicao-itens')
		self.assertEqual(response.context['edicao_itens']['pizzas'][0]['sabores'], [self.pizza.id])
		self.assertEqual(response.context['edicao_itens']['bebidas'][0]['bebida'], self.coca.id)

	def test_admin_troca_sabor_tamanho_e_borda(self):
		outra = Pizza.objects.create(nome='Frango Edit', ingredientes='Frango', disponivel=True)
		self.client.login(username='admin_edit', password='123456')
		self.client.post(reverse('pedido_editar', args=[self.pedido.id]), self._dados(**{
			'sabor_1[]': [str(outra.id)], 'tamanho[]': ['P'], 'borda_tipo[]': ['cheddar'],
			'quantidade[]': ['1'], 'bebida_id[]': [], 'bebida_quantidade[]': []}))
		self.pedido.refresh_from_db()
		item = self.pedido.itens.get()
		self.assertEqual(item.pizza, outra)
		self.assertEqual(item.tamanho, 'P')
		self.assertEqual(item.borda_tipo, 'cheddar')
		self.assertEqual(self.pedido.status, 'Em preparo')

	def test_edicao_atualiza_dados_itens_e_total_sem_alterar_o_andamento(self):
		self.client.login(username='admin_edit', password='123456')
		criado_em, numero_do_dia = self.pedido.criado_em, self.pedido.numero_do_dia

		response = self.client.post(reverse('pedido_editar', args=[self.pedido.id]), self._dados())

		self.assertRedirects(response, reverse('painel_pedidos'))
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Editado')
		self.assertEqual(self.pedido.local_entrega, self.taxa_b)
		self.assertEqual(self.pedido.taxa_entrega, Decimal('8.00'))
		self.assertEqual(self.pedido.subtotal, Decimal('86.00'))
		self.assertEqual(self.pedido.total, Decimal('94.00'))
		self.assertEqual(self.pedido.troco, '100,00')
		self.assertEqual(self.pedido.status, 'Em preparo')
		self.assertEqual(self.pedido.motoqueiro, self.motoqueiro)
		self.assertEqual(self.pedido.usuario, self.garcom)
		self.assertEqual(self.pedido.numero_do_dia, numero_do_dia)
		self.assertEqual(self.pedido.criado_em, criado_em)
		self.assertIsNone(self.pedido.reaberto_em)
		item = self.pedido.itens.get(item_tipo='pizza')
		self.assertEqual(item.quantidade, 2)
		self.assertEqual(item.observacao, 'Bem assada')

	def test_status_enviado_no_post_e_ignorado(self):
		self.client.login(username='admin_edit', password='123456')
		self.client.post(reverse('pedido_editar', args=[self.pedido.id]), self._dados(status='Pago', motoqueiro_id=''))
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.status, 'Em preparo')
		self.assertEqual(self.pedido.motoqueiro, self.motoqueiro)
		self.assertIsNone(self.pedido.fechado_em)

	def test_local_inalterado_mantem_taxa_original_mesmo_se_taxa_mudou(self):
		self.client.login(username='admin_edit', password='123456')
		TaxaEntrega.objects.filter(pk=self.taxa_a.pk).update(taxa='20.00')
		self.client.post(
			reverse('pedido_editar', args=[self.pedido.id]),
			self._dados(local_entrega=str(self.taxa_a.id)),
		)
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.taxa_entrega, Decimal('6.00'))

	def test_remover_itens_e_nao_deixar_pedido_vazio(self):
		self.client.login(username='admin_edit', password='123456')
		url = reverse('pedido_editar', args=[self.pedido.id])

		vazio = self.client.post(url, self._dados(**{
			'sabor_1[]': [], 'bebida_id[]': [], 'bebida_quantidade[]': []}))
		self.assertRedirects(vazio, url)
		self.assertEqual(self.pedido.itens.count(), 2)

		self.client.post(url, self._dados(**{
			'sabor_1[]': [], 'bebida_quantidade[]': ['3']}))
		self.pedido.refresh_from_db()
		self.assertFalse(self.pedido.itens.filter(item_tipo='pizza').exists())
		self.assertEqual(self.pedido.itens.get().quantidade, 3)
		self.assertEqual(self.pedido.subtotal, Decimal('24.00'))

	def test_erro_de_validacao_nao_grava_nada(self):
		self.client.login(username='admin_edit', password='123456')
		self.client.post(
			reverse('pedido_editar', args=[self.pedido.id]),
			self._dados(forma_pagamento='Fiado'),
		)
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Original')
		self.assertEqual(self.pedido.itens.count(), 2)

	def test_pedido_pago_nao_pode_ser_editado(self):
		Pedido.objects.filter(pk=self.pedido.pk).update(status='Pago')
		self.client.login(username='admin_edit', password='123456')
		url = reverse('pedido_editar', args=[self.pedido.id])
		self.assertRedirects(self.client.get(url), reverse('painel_pedidos'))
		self.client.post(url, self._dados())
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Original')

	def test_garcom_edita_igual_ao_admin_mas_so_o_proprio_pedido(self):
		outro = Pedido.objects.create(cliente='Pedido Alheio', total='10.00', usuario=self.admin)
		self.client.login(username='garcom_edit', password='123456')
		self.assertEqual(self.client.get(reverse('pedido_editar', args=[outro.id])).status_code, 404)

		url = reverse('pedido_editar', args=[self.pedido.id])
		self.assertTemplateUsed(self.client.get(url), 'pizzaria/pedido_form.html')
		self.client.post(url, self._dados())
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Editado')
		self.assertEqual(self.pedido.telefone, '84988887777')
		self.assertEqual(self.pedido.local_entrega, self.taxa_b)
		self.assertEqual(self.pedido.forma_pagamento, 'Dinheiro')
		self.assertEqual(self.pedido.total, Decimal('94.00'))
		self.assertEqual(self.pedido.status, 'Em preparo')
		self.assertEqual(self.pedido.usuario, self.garcom)

	def test_garcom_so_edita_pedido_pago_depois_de_reaberto(self):
		Pedido.objects.filter(pk=self.pedido.pk).update(status='Pago')
		self.client.login(username='garcom_edit', password='123456')
		url = reverse('pedido_editar', args=[self.pedido.id])
		self.assertRedirects(self.client.get(url), reverse('painel_pedidos'))
		self.client.post(url, self._dados())
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Original')

		self.client.post(reverse('pedido_reabrir', args=[self.pedido.id]), {'status': 'Em preparo'})
		self.assertEqual(self.client.get(url).status_code, 200)
		self.client.post(url, self._dados())
		self.pedido.refresh_from_db()
		self.assertEqual(self.pedido.cliente, 'Cliente Editado')
		self.assertEqual(self.pedido.status, 'Em preparo')

	def test_edicao_exige_login_e_lista_mostra_botao_editar(self):
		url = reverse('pedido_editar', args=[self.pedido.id])
		self.assertEqual(self.client.get(url).status_code, 302)
		self.client.login(username='admin_edit', password='123456')
		self.assertContains(self.client.get(reverse('painel_pedidos_lista') + '?filtro=todos'), url)


class CalculadoraPrecoTests(RateLimitIsolatedTestCase):
	def test_calcula_preco_com_sabor_especial_metade_e_adicionais(self):
		preco = calcular_preco_pizza(
			tamanho='G',
			sabores_especiais_count=1,
			total_sabores=2,
			borda_chocolate=True,
			catupiry_cima='metade',
			catupiry_borda=False,
		)
		# 39 base + 4 especial parcial + 10 borda chocolate + 7 catupiry metade
		self.assertEqual(preco, Decimal('60.00'))


class CheckoutCarrinhoTests(RateLimitIsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.pizza = Pizza.objects.create(
			nome='Calabresa Teste',
			ingredientes='Calabresa, cebola e azeitona',
			disponivel=True,
			especial=False,
		)

	def _popular_carrinho(self):
		session = self.client.session
		session['carrinho'] = {
			str(self.pizza.id): {
				'pizza_id': str(self.pizza.id),
				'quantidade': 1,
				'preco': '39.00',
				'tamanho': 'G',
				'borda_chocolate': False,
				'catupiry_cima': 'nao',
				'catupiry_borda': False,
				'sabores': None,
			}
		}
		session.save()

	def test_finalizar_exige_post(self):
		self._popular_carrinho()
		response = self.client.get(reverse('carrinho_finalizar'))
		self.assertEqual(response.status_code, 405)

	def test_remover_adicional_atualiza_preco_da_pizza(self):
		self._popular_carrinho()
		session = self.client.session
		session['carrinho'][str(self.pizza.id)].update({
			'preco': '53.00',
			'borda_chocolate': True,
			'catupiry_cima': 'metade',
		})
		session.save()

		response = self.client.post(
			reverse('carrinho_remover', args=[self.pizza.id]),
			data={'adicional': 'catupiry_cima'},
		)

		self.assertRedirects(response, reverse('carrinho_detalhes'))
		item = self.client.session['carrinho'][str(self.pizza.id)]
		self.assertEqual(item['preco'], '46.00')
		self.assertEqual(item['catupiry_cima'], 'nao')
		self.assertTrue(item['borda_chocolate'])

	def test_finalizar_cria_pedido_no_app(self):
		self._popular_carrinho()
		response = self.client.post(
			reverse('carrinho_finalizar'),
			data={
				'nome': 'Cliente Teste',
				'endereco': '',
				'observacoes': 'Sem cebola',
				'pagamento': 'PIX',
				'local_entrega': 'local',
			},
		)

		self.assertEqual(Pedido.objects.count(), 1)
		pedido = Pedido.objects.first()
		self.assertEqual(pedido.cliente, 'Cliente Teste')
		self.assertEqual(pedido.status, 'Em andamento')
		self.assertEqual(pedido.forma_pagamento, 'PIX')
		self.assertEqual(pedido.subtotal, Decimal('39.00'))
		self.assertEqual(pedido.total, Decimal('39.00'))
		self.assertRedirects(response, reverse('carrinho_detalhes'))
		pagina = self.client.get(reverse('carrinho_detalhes'))
		self.assertContains(pagina, 'Pedido em andamento')
		self.assertContains(pagina, 'Calabresa Teste')
		self.assertContains(pagina, 'PIX')

	def test_cliente_pode_acompanhar_dois_pedidos(self):
		taxa = TaxaEntrega.objects.create(nome='Frutuoso Gomes', taxa='6.00', ativo=True)
		self._popular_carrinho()
		self.client.post(
			reverse('carrinho_finalizar'),
			data={'nome': 'Cliente Um', 'endereco': 'Rua A', 'pagamento': 'PIX', 'local_entrega': str(taxa.id)},
		)

		session = self.client.session
		session['carrinho'] = {
			str(self.pizza.id): {
				'pizza_id': str(self.pizza.id), 'quantidade': 1, 'preco': '39.00', 'tamanho': 'G',
				'borda_chocolate': True, 'catupiry_cima': 'nao', 'catupiry_borda': False, 'sabores': None,
			}
		}
		session.save()
		self.client.post(
			reverse('carrinho_finalizar'),
			data={'nome': 'Cliente Dois', 'endereco': '', 'pagamento': 'Dinheiro', 'local_entrega': 'local', 'troco': '50,00'},
		)

		pagina = self.client.get(reverse('carrinho_detalhes'))
		self.assertContains(pagina, 'Pedido #001')
		self.assertContains(pagina, 'Pedido #002')
		self.assertContains(pagina, 'Frutuoso Gomes')
		self.assertContains(pagina, 'Borda de Chocolate')
		self.assertNotContains(pagina, 'Seu pedido ainda está vazio')

	def test_clientes_anonimos_nao_compartilham_pedido_em_andamento(self):
		taxa = TaxaEntrega.objects.create(nome='Lucrécia', taxa='5.00', ativo=True)
		cliente_a = Client()
		session_a = cliente_a.session
		session_a['carrinho'] = {
			str(self.pizza.id): {
				'pizza_id': str(self.pizza.id),
				'quantidade': 1,
				'preco': '39.00',
				'tamanho': 'G',
				'borda_chocolate': False,
				'catupiry_cima': 'nao',
				'catupiry_borda': False,
				'sabores': None,
			}
		}
		session_a.save()

		cliente_a.post(
			reverse('carrinho_finalizar'),
			data={
				'nome': 'Cliente A',
				'endereco': 'Rua A',
				'observacoes': '',
				'pagamento': 'PIX',
				'local_entrega': str(taxa.id),
			},
		)

		pagina_a = cliente_a.get(reverse('carrinho_detalhes'))
		self.assertContains(pagina_a, 'Pedido em andamento')
		self.assertContains(pagina_a, 'Pedido #')

		cliente_b = Client()
		pagina_b = cliente_b.get(reverse('carrinho_detalhes'))
		self.assertNotContains(pagina_b, 'Pedido em andamento')
		self.assertContains(pagina_b, 'Pedido Vazio')


class PainelBebidasTests(RateLimitIsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.user = get_user_model().objects.create_user(username='admin', password='123456')

	def test_bebida_pode_ter_imagem(self):
		bebida = Bebida.objects.create(
			nome='Refrigerante Teste',
			descricao='Lata 350ml',
			preco='8.50',
			disponivel=True,
			imagem=SimpleUploadedFile('refrigerante.png', b'fake-image-content', content_type='image/png'),
		)
		self.assertTrue(bebida.imagem)
		self.assertTrue(bebida.imagem.name.endswith('.png'))

	def test_pedido_finalizado_inclui_bebida_selecionada(self):
		pizza = Pizza.objects.create(
			nome='Calabresa',
			ingredientes='Calabresa',
			disponivel=True,
			especial=False,
		)
		bebida = Bebida.objects.create(
			nome='Coca-Cola',
			descricao='Lata 350ml',
			preco='8.50',
			disponivel=True,
		)
		response = self.client.post(
			reverse('carrinho_adicionar_pizza'),
			data={
				'acao': 'pedido',
				'tamanho': 'G',
				'num_sabores': '1',
				'sabor_1': str(pizza.id),
				'quer_bebida': 'sim',
				'bebida_id[]': [str(bebida.id)],
				'catupiry_cima': 'nao',
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		carrinho = self.client.session.get('carrinho', {})
		self.assertGreater(len(carrinho), 1)
		self.assertTrue(any(item.get('bebida_id') == str(bebida.id) for item in carrinho.values()))

	def test_pedido_finalizado_inclui_multiplas_bebidas(self):
		pizza = Pizza.objects.create(
			nome='Marguerita',
			ingredientes='Mussarela e tomate',
			disponivel=True,
			especial=False,
		)
		coca = Bebida.objects.create(nome='Coca-Cola', preco='8.50', disponivel=True)
		guarana = Bebida.objects.create(nome='Guaraná', preco='7.00', disponivel=True)

		response = self.client.post(
			reverse('carrinho_adicionar_pizza'),
			data={
				'acao': 'pedido',
				'tamanho': 'G',
				'num_sabores': '1',
				'sabor_1': str(pizza.id),
				'quer_bebida': 'sim',
				'bebida_id[]': [str(coca.id), str(guarana.id)],
				'catupiry_cima': 'nao',
			},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		carrinho = self.client.session.get('carrinho', {})
		bebida_ids_no_carrinho = {item.get('bebida_id') for item in carrinho.values() if item.get('bebida_id')}
		self.assertEqual(bebida_ids_no_carrinho, {str(coca.id), str(guarana.id)})

	def test_pedido_manual_salva_entrega_pagamento_e_taxa(self):
		pizza = Pizza.objects.create(nome='Calabresa Manual', ingredientes='Calabresa', disponivel=True)
		taxa = TaxaEntrega.objects.create(nome='Bairro Teste', taxa='5.00', ativo=True)
		self.client.login(username='admin', password='123456')

		response = self.client.post(
			reverse('pedido_adicionar'),
			data={
				'cliente': 'Cliente Manual',
				'telefone': '84999999999',
				'local_entrega': str(taxa.id),
				'endereco': 'Rua Teste, 10',
				'forma_pagamento': 'Dinheiro',
				'troco': '50,00',
				'sabor_1[]': [str(pizza.id)],
				'num_sabores[]': ['1'],
				'tamanho[]': ['G'],
				'quantidade[]': ['1'],
			},
		)

		pedido = Pedido.objects.get(cliente='Cliente Manual')
		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertEqual(pedido.local_entrega, taxa)
		self.assertEqual(pedido.forma_pagamento, 'Dinheiro')
		self.assertEqual(pedido.troco, '50,00')
		self.assertEqual(pedido.subtotal, Decimal('39.00'))
		self.assertEqual(pedido.total, Decimal('44.00'))

	def test_registro_manual_nao_exibe_telefone_e_salva_sem_telefone(self):
		pizza = Pizza.objects.create(nome='Calabresa Sem Telefone', ingredientes='Calabresa', disponivel=True)
		self.client.login(username='admin', password='123456')

		formulario = self.client.get(reverse('pedido_adicionar'))
		self.assertNotContains(formulario, 'id="telefone"')

		response = self.client.post(
			reverse('pedido_adicionar'),
			data={
				'cliente': 'Cliente Sem Telefone',
				'local_entrega': 'local',
				'forma_pagamento': 'PIX',
				'sabor_1[]': [str(pizza.id)],
				'num_sabores[]': ['1'],
				'tamanho[]': ['G'],
				'quantidade[]': ['1'],
			},
		)

		pedido = Pedido.objects.get(cliente='Cliente Sem Telefone')
		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertEqual(pedido.telefone, '')

	def test_garcom_registra_pedido_sem_telefone_e_endereco(self):
		pizza = Pizza.objects.create(nome='Calabresa Garcom', ingredientes='Calabresa', disponivel=True)
		garcom = get_user_model().objects.create_user(username='garcom_sem_dados', password='senha123')
		garcom.groups.create(name='Garçons')
		self.client.login(username='garcom_sem_dados', password='senha123')

		response = self.client.post(
			reverse('pedido_adicionar'),
			data={
				'cliente': 'Cliente Garcom',
				'sabor_1[]': [str(pizza.id)],
				'num_sabores[]': ['1'],
				'tamanho[]': ['G'],
				'quantidade[]': ['1'],
			},
		)

		pedido = Pedido.objects.get(cliente='Cliente Garcom')
		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertEqual(pedido.telefone, '')
		self.assertEqual(pedido.endereco, '')

	def test_pedido_manual_salva_adicionais_da_pizza(self):
		pizza = Pizza.objects.create(nome='Calabresa Adicionais', ingredientes='Calabresa', disponivel=True)
		self.client.login(username='admin', password='123456')

		response = self.client.post(
			reverse('pedido_adicionar'),
			data={
				'cliente': 'Cliente Adicionais',
				'local_entrega': 'local',
				'forma_pagamento': 'PIX',
				'sabor_1[]': [str(pizza.id)],
				'num_sabores[]': ['1'],
				'tamanho[]': ['G'],
				'quantidade[]': ['1'],
				'borda_chocolate[]': ['sim'],
				'catupiry_cima[]': ['metade'],
				'catupiry_borda[]': ['sim'],
			},
		)

		pedido = Pedido.objects.get(cliente='Cliente Adicionais')
		item = pedido.itens.get()
		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertTrue(item.borda_chocolate)
		self.assertEqual(item.catupiry_cima, 'metade')
		self.assertFalse(item.catupiry_borda)
		self.assertEqual(pedido.total, Decimal('56.00'))

	def test_impressao_exibe_tres_sabores(self):
		pizzas = [
			Pizza.objects.create(nome=nome, ingredientes='Ingredientes', disponivel=True)
			for nome in ('Sabor Um', 'Sabor Dois', 'Sabor Tres')
		]
		pedido = Pedido.objects.create(
			cliente='Cliente Sabores',
			total='39.00',
			forma_pagamento='Dinheiro',
			troco='50,00',
		)
		ItemPedido.objects.create(
			pedido=pedido,
			pizza=pizzas[0],
			preco_unitario='39.00',
			sabores=json.dumps({
				'num_sabores': 3,
				'ids': [pizza.id for pizza in pizzas],
				'nomes': [pizza.nome for pizza in pizzas],
			}),
		)
		self.client.login(username='admin', password='123456')

		response = self.client.get(reverse('pedido_imprimir', args=[pedido.id]))

		self.assertContains(response, '1/3 SABOR UM')
		self.assertContains(response, '1/3 SABOR DOIS')
		self.assertContains(response, '1/3 SABOR TRES')
		self.assertContains(response, 'Troco para:')
		self.assertContains(response, '50,00')

	def test_painel_bebidas_exige_login(self):
		response = self.client.get(reverse('painel_bebidas'))
		self.assertEqual(response.status_code, 302)

	def test_dono_cadastra_garcom_e_garcom_tem_acesso_restrito(self):
		self.client.login(username='admin', password='123456')
		response = self.client.post(
			reverse('garcom_adicionar'),
			data={'nome': 'Joao Garcom', 'senha': 'senha123'},
		)
		self.assertRedirects(response, reverse('painel_garcons'))

		garcom = get_user_model().objects.get(username='Joao Garcom')
		self.assertTrue(garcom.groups.filter(name='Garçons').exists())

		self.client.logout()
		self.client.login(username='Joao Garcom', password='senha123')
		self.assertRedirects(self.client.get(reverse('painel')), reverse('painel_pedidos'))
		self.assertEqual(self.client.get(reverse('painel_pedidos')).status_code, 200)
		self.assertEqual(self.client.get(reverse('historico_pedidos')).status_code, 200)
		self.assertRedirects(self.client.get(reverse('painel_bebidas')), reverse('painel_pedidos'))
		self.assertRedirects(self.client.get(reverse('pedido_adicionar')), reverse('painel_pedidos'))

	def test_pedido_pago_sai_dos_ativos_e_fica_no_historico(self):
		pedido = Pedido.objects.create(cliente='Cliente Pago', total='39.00')
		self.client.login(username='admin', password='123456')

		response = self.client.post(
			reverse('pedido_alterar_status', args=[pedido.id]),
			data={'status': 'Pago'},
		)

		self.assertRedirects(response, reverse('painel_pedidos'))
		ativos = self.client.get(reverse('painel_pedidos') + '?filtro=todos')
		historico = self.client.get(reverse('historico_pedidos'))
		self.assertNotContains(ativos, 'Cliente Pago')
		self.assertContains(historico, 'Cliente Pago')

	def test_pedido_reaberto_hoje_aparece_no_filtro_hoje(self):
		pedido = Pedido.objects.create(cliente='Cliente Reaberto Hoje', total='39.00', status='Em preparo')
		pedido.criado_em = timezone.now() - timedelta(days=2)
		pedido.reaberto_em = timezone.now()
		pedido.save(update_fields=['criado_em', 'reaberto_em'])
		self.client.login(username='admin', password='123456')

		response = self.client.get(reverse('painel_pedidos') + '?filtro=hoje')

		self.assertContains(response, 'Cliente Reaberto Hoje')

	def test_dono_pode_excluir_pedido(self):
		pedido = Pedido.objects.create(cliente='Cliente Removido', total='39.00')
		self.client.login(username='admin', password='123456')

		response = self.client.post(reverse('pedido_excluir', args=[pedido.id]))

		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertFalse(Pedido.objects.filter(id=pedido.id).exists())

	def test_garcom_nao_pode_excluir_pedido(self):
		pedido = Pedido.objects.create(cliente='Cliente Protegido', total='39.00')
		garcom = get_user_model().objects.create_user(username='garcom_exclusao', password='senha123')
		garcom.groups.create(name='Garçons')
		self.client.login(username='garcom_exclusao', password='senha123')

		response = self.client.post(reverse('pedido_excluir', args=[pedido.id]))

		self.assertRedirects(response, reverse('painel_pedidos'))
		self.assertTrue(Pedido.objects.filter(id=pedido.id).exists())

	def test_pedido_pago_pode_ser_reaberto_com_novo_status(self):
		pedido = Pedido.objects.create(cliente='Cliente Reaberto', total='39.00', status='Pago')
		self.client.login(username='admin', password='123456')

		response = self.client.post(
			reverse('pedido_reabrir', args=[pedido.id]),
			data={'status': 'Em preparo'},
		)

		self.assertRedirects(response, reverse('historico_pedidos'))
		pedido.refresh_from_db()
		self.assertEqual(pedido.status, 'Em preparo')
		self.assertIsNotNone(pedido.reaberto_em)
		self.client.post(
			reverse('pedido_reabrir', args=[pedido.id]),
			data={'status': 'Pago'},
		)

	def test_pedido_entregue_continua_ativo_ate_ser_pago(self):
		pedido = Pedido.objects.create(cliente='Cliente Entregue', total='39.00')
		self.client.login(username='admin', password='123456')

		self.client.post(
			reverse('pedido_alterar_status', args=[pedido.id]),
			data={'status': 'Entregue'},
		)
		ativos = self.client.get(reverse('painel_pedidos') + '?filtro=todos')
		self.assertContains(ativos, 'Cliente Entregue')

		self.client.post(
			reverse('pedido_alterar_status', args=[pedido.id]),
			data={'status': 'Pago'},
		)
		ativos = self.client.get(reverse('painel_pedidos') + '?filtro=todos')
		self.assertNotContains(ativos, 'Cliente Entregue')

	def test_painel_bebidas_exibe_lista_para_admin(self):
		self.client.login(username='admin', password='123456')
		response = self.client.get(reverse('painel_bebidas'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Gerenciar Bebidas')


class ContatoTests(RateLimitIsolatedTestCase):
	def test_contato_exige_telefone_valido(self):
		response = self.client.post(
			reverse('contato'),
			data={
				'nome': 'Cliente Teste',
				'telefone': '123',
				'mensagem': 'Quero saber o horario.',
			},
		)
		self.assertRedirects(response, reverse('contato'))

	def test_contato_redireciona_com_telefone_no_whatsapp(self):
		response = self.client.post(
			reverse('contato'),
			data={
				'nome': 'Cliente Teste',
				'telefone': '(84) 99999-9999',
				'mensagem': 'Quero fazer uma reserva.',
			},
		)
		self.assertEqual(response.status_code, 302)
		self.assertIn('wa.me/5584990346414?text=', response.url)
		self.assertIn('Telefone%3A%20%2884%29%2099999-9999', response.url)
