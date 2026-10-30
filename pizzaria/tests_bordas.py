from decimal import Decimal

from django.template.loader import get_template
from django.test import TestCase

from .calculadora_preco import calcular_preco_pizza
from .carrinho import formatar_moeda, rotulo_borda, valor_borda, valor_catupiry_cima
from .models import ConfiguracaoPreco, ItemPedido, Pizza


class BordasECarrinhoTests(TestCase):
    def setUp(self):
        self.pizza = Pizza.objects.create(
            nome='Calabresa Validacao',
            ingredientes='Calabresa, cebola e mussarela',
            disponivel=True,
        )
        self.pizza2 = Pizza.objects.create(
            nome='Mussarela Validacao',
            ingredientes='Mussarela e oregano',
            disponivel=True,
        )

    def _adicionar_pizza(self, pizza=None, **extra):
        dados = {
            'tamanho': 'G',
            'num_sabores': '1',
            'sabor_1': str((pizza or self.pizza).id),
            'borda_tipo': 'catupiry',
            'catupiry_cima': 'nao',
            'quer_bebida': 'nao',
        }
        dados.update(extra)
        return self.client.post('/carrinho/adicionar-pizza/', dados)

    def _item_id(self, indice=0):
        return list(self.client.session['carrinho'].keys())[indice]

    def test_templates_compilam(self):
        for nome in [
            'pizzaria/carrinho.html',
            'pizzaria/escolher_sabores.html',
            'pizzaria/pedido_imprimir.html',
            'pizzaria/painel_pedidos.html',
            'pizzaria/historico_pedidos.html',
        ]:
            get_template(nome)

    def test_tela_de_escolha_tem_as_quatro_bordas(self):
        pagina = self.client.get('/escolher-sabores/').content.decode('utf-8')
        self.assertIn('name="borda_tipo"', pagina)
        self.assertIn('id="borda_tipo" value="catupiry"', pagina)
        for valor in ['cheddar', 'sem_borda', 'catupiry_original', 'chocolate']:
            self.assertIn(f'value="{valor}"', pagina)
        # Catupiry é a escolha implícita: não existe checkbox para ele.
        self.assertNotIn('name="borda_catupiry"', pagina)
        self.assertIn('class="borda-option-input"', pagina)
        self.assertIn('selecionarBorda', pagina)
        self.assertNotIn('controlarBordas', pagina)

    def test_valores_das_bordas(self):
        config = ConfiguracaoPreco.obter()
        self.assertEqual(valor_borda('G', 'catupiry', config), Decimal('0.00'))
        self.assertEqual(valor_borda('G', 'cheddar', config), Decimal('0.00'))
        self.assertEqual(valor_borda('G', 'sem_borda', config), Decimal('0.00'))
        self.assertEqual(valor_borda('P', 'catupiry_original', config), Decimal('10.00'))
        self.assertEqual(valor_borda('M', 'catupiry_original', config), Decimal('12.00'))
        self.assertEqual(valor_borda('G', 'catupiry_original', config), Decimal('14.00'))
        self.assertEqual(valor_borda('G', 'chocolate', config), Decimal('10.00'))
        self.assertEqual(valor_catupiry_cima('G', 'inteira', config), Decimal('14.00'))
        self.assertEqual(valor_catupiry_cima('G', 'metade', config), Decimal('7.00'))
        self.assertEqual(formatar_moeda('10.00'), '10,00')
        self.assertEqual(rotulo_borda('cheddar'), 'Borda de Cheddar')
        self.assertEqual(rotulo_borda('catupiry_original'), 'Borda de Catupiry Original')

    def test_borda_paga_e_observacao_no_carrinho(self):
        self.assertEqual(
            self._adicionar_pizza(
                borda_tipo='catupiry_original',
                observacao='Sem cebola, bem assada',
            ).status_code,
            302,
        )

        item = self.client.session['carrinho'][self._item_id()]
        self.assertEqual(item['borda_tipo'], 'catupiry_original')
        self.assertTrue(item['catupiry_borda'])
        self.assertEqual(item['observacao'], 'Sem cebola, bem assada')
        self.assertEqual(
            Decimal(item['preco']),
            calcular_preco_pizza('G', 0, 1, borda_tipo='catupiry_original'),
        )

        pagina = self.client.get('/carrinho/').content.decode('utf-8')
        self.assertIn('Borda de Catupiry Original', pagina)
        self.assertIn('Sem cebola, bem assada', pagina)
        self.assertIn('R$ 14,00', pagina)
        self.assertIn('wa-item', pagina)
        self.assertIn('value="borda"', pagina)

    def test_padrao_sem_selecao_e_cheddar_sao_gratis(self):
        # Nenhuma checkbox marcada = Catupiry padrão, inclusa e sem linha de adicional.
        self._adicionar_pizza(pizza=self.pizza, borda_tipo='')
        self._adicionar_pizza(pizza=self.pizza2, borda_tipo='cheddar')

        pagina = self.client.get('/carrinho/').content.decode('utf-8')
        self.assertIn('Borda de Cheddar', pagina)
        self.assertNotIn('Borda de Catupiry (padrão)', pagina)
        self.assertIn('Grátis', pagina)

        itens = list(self.client.session['carrinho'].values())
        self.assertEqual(itens[0]['borda_tipo'], 'catupiry')
        self.assertEqual(itens[1]['borda_tipo'], 'cheddar')
        for item in itens:
            self.assertEqual(
                Decimal(item['preco']),
                calcular_preco_pizza('G', 0, 1, borda_tipo=item['borda_tipo']),
            )

    def test_remover_borda_devolve_o_valor(self):
        self._adicionar_pizza(borda_tipo='chocolate')
        item_id = self._item_id()
        preco_com_borda = Decimal(self.client.session['carrinho'][item_id]['preco'])

        resposta = self.client.post(f'/carrinho/remover/{item_id}/', {'adicional': 'borda'})
        self.assertEqual(resposta.status_code, 302)

        item = self.client.session['carrinho'][item_id]
        self.assertEqual(item['borda_tipo'], 'sem_borda')
        self.assertFalse(item['borda_chocolate'])
        self.assertEqual(
            preco_com_borda - Decimal(item['preco']),
            valor_borda('G', 'chocolate'),
        )

        pagina = self.client.get('/carrinho/').content.decode('utf-8')
        self.assertNotIn('Borda de Chocolate', pagina)

    def test_finalizar_grava_borda_e_observacao_no_item(self):
        self._adicionar_pizza(
            borda_tipo='catupiry_original',
            observacao='Cortar em 8 fatias',
        )
        resposta = self.client.post('/carrinho/finalizar/', {
            'nome': 'Cliente Validacao',
            'local_entrega': 'local',
            'pagamento': 'PIX',
            'troco': '',
        })
        self.assertEqual(resposta.status_code, 302)

        item = ItemPedido.objects.get()
        self.assertEqual(item.borda_tipo, 'catupiry_original')
        self.assertTrue(item.catupiry_borda)
        self.assertEqual(item.observacao, 'Cortar em 8 fatias')
        self.assertEqual(item.tamanho, 'G')

    def test_sem_borda_aparece_nos_adicionais(self):
        self._adicionar_pizza(borda_tipo='sem_borda')
        item = self.client.session['carrinho'][self._item_id()]
        self.assertEqual(item['borda_tipo'], 'sem_borda')
        self.assertEqual(
            Decimal(item['preco']),
            calcular_preco_pizza('G', 0, 1, borda_tipo='sem_borda'),
        )

        pagina = self.client.get('/carrinho/').content.decode('utf-8')
        self.assertIn('<strong>Adicionais:</strong>', pagina)
        self.assertIn('Sem borda', pagina)
        self.assertIn('| Sem borda', pagina)  # também entra na mensagem do WhatsApp

    def test_todas_as_bordas_desmarcadas_ficam_no_padrao(self):
        # Nenhuma marcada: o campo oculto vai como "catupiry" (padrão da casa).
        self._adicionar_pizza(borda_tipo='catupiry')
        item = self.client.session['carrinho'][self._item_id()]
        self.assertEqual(item['borda_tipo'], 'catupiry')
        self.assertFalse(item['borda_chocolate'])
        self.assertFalse(item['catupiry_borda'])

        pagina = self.client.get('/carrinho/').content.decode('utf-8')
        self.assertNotIn('<strong>Adicionais:</strong>', pagina)

    def test_sem_campo_de_borda_usa_o_padrao_da_casa(self):
        self._adicionar_pizza(pizza=self.pizza2, borda_tipo='')
        item = self.client.session['carrinho'][self._item_id()]
        self.assertEqual(item['borda_tipo'], 'catupiry')
