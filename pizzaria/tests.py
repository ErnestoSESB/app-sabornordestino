from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from .calculadora_preco import calcular_preco_pizza
from .models import Bebida, ItemPedido, Pedido, Pizza, TaxaEntrega


class CalculadoraPrecoTests(TestCase):
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


class CheckoutCarrinhoTests(TestCase):
	def setUp(self):
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


class PainelBebidasTests(TestCase):
	def setUp(self):
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

	def test_impressao_exibe_tres_sabores(self):
		pizzas = [
			Pizza.objects.create(nome=nome, ingredientes='Ingredientes', disponivel=True)
			for nome in ('Sabor Um', 'Sabor Dois', 'Sabor Tres')
		]
		pedido = Pedido.objects.create(cliente='Cliente Sabores', total='39.00')
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

		self.assertContains(response, 'Sabor Um')
		self.assertContains(response, 'Sabor Dois')
		self.assertContains(response, 'Sabor Tres')

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


class ContatoTests(TestCase):
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
