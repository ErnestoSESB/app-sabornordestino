from decimal import Decimal
from .models import Pizza, Bebida
import json

class Carrinho:
    def __init__(self, request):
        self.session = request.session
        carrinho = self.session.get('carrinho')
        if not carrinho:
            carrinho = self.session['carrinho'] = {}
        self.carrinho = carrinho
    
    def adicionar(self, pizza=None, bebida=None, quantidade=1, preco=None, tamanho='G', borda_chocolate=False,
                  catupiry_cima='nao', catupiry_borda=False, sabores=None):
        if bebida is not None:
            bebida_id = str(bebida.id)
            item_id = f"bebida_{bebida_id}"
            if item_id not in self.carrinho:
                self.carrinho[item_id] = {
                    'tipo': 'bebida',
                    'bebida_id': bebida_id,
                    'pizza_id': None,
                    'quantidade': quantidade,
                    'preco': str(preco if preco is not None else bebida.preco),
                    'tamanho': tamanho,
                    'borda_chocolate': False,
                    'catupiry_cima': 'nao',
                    'catupiry_borda': False,
                    'sabores': None,
                    'nome': bebida.nome,
                }
            else:
                self.carrinho[item_id]['quantidade'] += quantidade
            self.salvar()
            return

        pizza_id = str(pizza.id)
        if sabores:
            import time
            item_id = f"{pizza_id}_{int(time.time() * 1000)}"
        else:
            item_id = pizza_id

        if item_id not in self.carrinho:
            self.carrinho[item_id] = {
                'tipo': 'pizza',
                'pizza_id': pizza_id,
                'bebida_id': None,
                'quantidade': quantidade,
                'preco': str(preco if preco is not None else pizza.get_preco(tamanho)),
                'tamanho': tamanho,
                'borda_chocolate': borda_chocolate,
                'catupiry_cima': catupiry_cima,
                'catupiry_borda': catupiry_borda,
                'sabores': sabores,
                'nome': pizza.nome,
            }
        else:
            self.carrinho[item_id]['quantidade'] += quantidade
        self.salvar()
    
    def remover(self, item_id):
        if item_id in self.carrinho:
            del self.carrinho[item_id]
            self.salvar()

    def remover_adicional(self, item_id, adicional):
        item = self.carrinho.get(item_id)
        adicionais_validos = {'borda_chocolate', 'catupiry_cima', 'catupiry_borda'}

        if not item or item.get('tipo', 'pizza') == 'bebida' or adicional not in adicionais_validos:
            return

        tamanho = item.get('tamanho', 'G')
        precos = {
            'borda_chocolate': {'P': Decimal('4.00'), 'M': Decimal('5.00'), 'G': Decimal('6.00')},
            'catupiry_borda': {'P': Decimal('8.00'), 'M': Decimal('10.00'), 'G': Decimal('12.00')},
        }
        valor = precos.get(adicional, {}).get(tamanho, Decimal('0.00'))

        if adicional == 'catupiry_cima':
            valor = {
                'inteira': {'P': Decimal('10.00'), 'M': Decimal('12.00'), 'G': Decimal('14.00')},
                'metade': {'P': Decimal('5.00'), 'M': Decimal('6.00'), 'G': Decimal('7.00')},
            }.get(item.get('catupiry_cima'), {}).get(tamanho, Decimal('0.00'))

        item['preco'] = str(max(Decimal('0.00'), Decimal(item.get('preco', '0.00')) - valor))
        if adicional == 'catupiry_cima':
            item['catupiry_cima'] = 'nao'
        else:
            item[adicional] = False
        self.salvar()
    
    def atualizar_quantidade(self, item_id, quantidade):
        if item_id in self.carrinho:
            self.carrinho[item_id]['quantidade'] = quantidade
            self.salvar()
    
    def salvar(self):
        self.session.modified = True
    
    def limpar(self):
        del self.session['carrinho']
        self.salvar()
    
    def __iter__(self):
        pizza_ids = [item['pizza_id'] for item in self.carrinho.values() if item.get('pizza_id')]
        bebida_ids = [item['bebida_id'] for item in self.carrinho.values() if item.get('bebida_id')]
        pizzas = Pizza.objects.filter(id__in=pizza_ids)
        bebidas = Bebida.objects.filter(id__in=bebida_ids)
        pizzas_dict = {str(p.id): p for p in pizzas}
        bebidas_dict = {str(b.id): b for b in bebidas}

        for item_id, item_data in self.carrinho.items():
            item = item_data.copy()
            item['item_id'] = item_id
            item['pizza'] = pizzas_dict.get(item.get('pizza_id'))
            item['bebida'] = bebidas_dict.get(item.get('bebida_id'))
            item['preco'] = Decimal(item.get('preco', '0'))
            item['total'] = item['preco'] * item['quantidade']
            yield item
    
    def __len__(self):
        return sum(item['quantidade'] for item in self.carrinho.values())
    
    def get_total(self):
        return sum(Decimal(item.get('preco', '0')) * item['quantidade'] for item in self.carrinho.values())
