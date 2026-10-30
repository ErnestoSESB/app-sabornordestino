from decimal import Decimal
from .models import Pizza, Bebida, ConfiguracaoPreco
from .calculadora_preco import valor_por_tamanho
import json

# Borda padrão da casa (já inclusa no valor da pizza).
BORDA_PADRAO = 'catupiry'

BORDAS_LABELS = {
    'catupiry': 'Borda de Catupiry (padrão)',
    'cheddar': 'Borda de Cheddar',
    'sem_borda': 'Sem borda',
    'catupiry_original': 'Borda de Catupiry Original',
    'chocolate': 'Borda de Chocolate',
}

BORDAS_PREFIXOS = {
    'catupiry': 'borda_catupiry',
    'cheddar': 'borda_cheddar',
    'catupiry_original': 'borda_catupiry_original',
    'chocolate': 'borda_chocolate',
}


def rotulo_borda(borda_tipo):
    return BORDAS_LABELS.get(borda_tipo or BORDA_PADRAO, BORDAS_LABELS[BORDA_PADRAO])


def resolver_borda_tipo(item):
    """Descobre a borda do item, considerando carrinhos antigos sem o campo borda_tipo."""
    borda_tipo = item.get('borda_tipo')
    if borda_tipo:
        return borda_tipo
    if item.get('borda_chocolate'):
        return 'chocolate'
    if item.get('catupiry_borda'):
        return 'catupiry_original'
    return BORDA_PADRAO


def valor_borda(tamanho, borda_tipo, configuracao=None):
    prefixo = BORDAS_PREFIXOS.get(borda_tipo)
    if not prefixo:
        return Decimal('0.00')
    if configuracao is None:
        configuracao = ConfiguracaoPreco.obter()
    return Decimal(valor_por_tamanho(configuracao, prefixo, tamanho))


def valor_catupiry_cima(tamanho, catupiry_cima, configuracao=None):
    if catupiry_cima not in {'metade', 'inteira'}:
        return Decimal('0.00')
    if configuracao is None:
        configuracao = ConfiguracaoPreco.obter()
    return Decimal(valor_por_tamanho(configuracao, f'catupiry_cima_{catupiry_cima}', tamanho))


def formatar_moeda(valor):
    try:
        return f'{Decimal(str(valor)):.2f}'.replace('.', ',')
    except (TypeError, ValueError, ArithmeticError):
        return '0,00'


class Carrinho:
    def __init__(self, request):
        self.session = request.session
        carrinho = self.session.get('carrinho')
        if not carrinho:
            carrinho = self.session['carrinho'] = {}
        self.carrinho = carrinho
    
    def adicionar(self, pizza=None, bebida=None, quantidade=1, preco=None, tamanho='G', borda_chocolate=False,
                  catupiry_cima='nao', catupiry_borda=False, sabores=None, borda_tipo='catupiry', observacao=''):
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
                    'borda_tipo': 'catupiry',
                    'sabores': None,
                    'nome': bebida.nome,
                    'observacao': observacao,
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
                'borda_tipo': borda_tipo,
                'sabores': sabores,
                'nome': pizza.nome,
                'observacao': observacao,
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
        adicionais_validos = {'borda', 'borda_chocolate', 'catupiry_cima', 'catupiry_borda'}

        if not item or item.get('tipo', 'pizza') == 'bebida' or adicional not in adicionais_validos:
            return

        tamanho = item.get('tamanho', 'G')
        configuracao = ConfiguracaoPreco.obter()

        # Bordas: qualquer opção volta para "sem borda" e devolve o valor cobrado.
        if adicional in {'borda', 'borda_chocolate', 'catupiry_borda'}:
            if adicional == 'borda_chocolate':
                borda_tipo = 'chocolate'
            elif adicional == 'catupiry_borda':
                borda_tipo = 'catupiry_original'
            else:
                borda_tipo = resolver_borda_tipo(item)

            valor = valor_borda(tamanho, borda_tipo, configuracao)
            item['preco'] = str(max(Decimal('0.00'), Decimal(item.get('preco', '0.00')) - valor))
            item['borda_tipo'] = 'sem_borda'
            item['borda_chocolate'] = False
            item['catupiry_borda'] = False
            self.salvar()
            return

        # Catupiry original por cima.
        valor = valor_catupiry_cima(tamanho, item.get('catupiry_cima'), configuracao)
        item['preco'] = str(max(Decimal('0.00'), Decimal(item.get('preco', '0.00')) - valor))
        item['catupiry_cima'] = 'nao'
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
