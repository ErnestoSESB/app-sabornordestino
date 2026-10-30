from decimal import Decimal
from .models import ConfiguracaoPreco


def valor_por_tamanho(configuracao, prefixo, tamanho):
    tamanho = tamanho.lower()
    return getattr(configuracao, f'{prefixo}_{tamanho}')


def calcular_preco_pizza(
    tamanho,
    sabores_especiais_count,
    total_sabores,
    borda_chocolate=False,
    catupiry_cima='nao',
    catupiry_borda=False,
    borda_tipo=None,
):
    if tamanho not in {'P', 'M', 'G'}:
        tamanho = 'G'

    configuracao = ConfiguracaoPreco.obter()

    # Valor base da pizza.
    preco = valor_por_tamanho(configuracao, 'preco', tamanho)

    # Acréscimo por sabores especiais.
    if sabores_especiais_count > 0:
        if sabores_especiais_count == total_sabores:
            preco += valor_por_tamanho(
                configuracao,
                'especial_total',
                tamanho,
            )
        else:
            preco += valor_por_tamanho(
                configuracao,
                'especial_parcial',
                tamanho,
            )

    # Compatibilidade com pedidos/códigos antigos.
    if borda_tipo is None:
        if borda_chocolate:
            borda_tipo = 'chocolate'
        elif catupiry_borda:
            borda_tipo = 'catupiry_original'
        else:
            borda_tipo = 'catupiry'

    # Valor da borda selecionada.
    prefixos_borda = {
        'catupiry': 'borda_catupiry',
        'cheddar': 'borda_cheddar',
        'catupiry_original': 'borda_catupiry_original',
        'chocolate': 'borda_chocolate',
    }

    prefixo_borda = prefixos_borda.get(borda_tipo)
    if prefixo_borda:
        preco += valor_por_tamanho(configuracao, prefixo_borda, tamanho)

    # Catupiry original por cima.
    if catupiry_cima == 'metade':
        preco += valor_por_tamanho(
            configuracao,
            'catupiry_cima_metade',
            tamanho,
        )
    elif catupiry_cima == 'inteira':
        preco += valor_por_tamanho(
            configuracao,
            'catupiry_cima_inteira',
            tamanho,
        )

    return preco