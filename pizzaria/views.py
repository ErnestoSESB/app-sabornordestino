from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from datetime import datetime, timedelta
from datetime import date as date_type
from html import unescape
from .models import Pizza, Pedido, ItemPedido, Bebida, TaxaEntrega
from .carrinho import (
	Carrinho,
	formatar_moeda,
	resolver_borda_tipo,
	rotulo_borda,
	valor_borda,
	valor_catupiry_cima,
)
from .calculadora_preco import calcular_preco_pizza
from urllib.parse import quote
import json
import uuid
import re
from functools import wraps
from .models import Usuario, Motoqueiro 
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from .models import Pizza, Pedido, ItemPedido, Bebida, TaxaEntrega, ConfiguracaoPreco, gerar_numero_pedido_diario



def precos_para_javascript():
    configuracao = ConfiguracaoPreco.obter()

    def por_tamanho(prefixo):
        return {
            'P': float(getattr(configuracao, f'{prefixo}_p')),
            'M': float(getattr(configuracao, f'{prefixo}_m')),
            'G': float(getattr(configuracao, f'{prefixo}_g')),
        }

    return json.dumps({
        'base': por_tamanho('preco'),
        'especial_parcial': por_tamanho('especial_parcial'),
        'especial_total': por_tamanho('especial_total'),
        'borda_catupiry': por_tamanho('borda_catupiry'),
        'borda_cheddar': por_tamanho('borda_cheddar'),
        'borda_catupiry_original': por_tamanho('borda_catupiry_original'),
        'borda_chocolate': por_tamanho('borda_chocolate'),
        'catupiry_metade': por_tamanho('catupiry_cima_metade'),
        'catupiry_inteira': por_tamanho('catupiry_cima_inteira'),
    })

def garcom_user(user):
	return user.is_authenticated and user.groups.filter(name='Garçons').exists()


def dono_required(view_func):
	@wraps(view_func)
	def wrapped(request, *args, **kwargs):
		if not request.user.is_authenticated:
			return redirect(f"/login/?next={request.path}")
		if garcom_user(request.user):
			return redirect('painel_pedidos')
		return view_func(request, *args, **kwargs)
	return wrapped


def _ensure_cart_device_owner(request):
	cliente_token = request.session.get('cliente_token')
	if not cliente_token:
		cliente_token = uuid.uuid4().hex
		request.session['cliente_token'] = cliente_token

	carrinho_owner = request.session.get('carrinho_owner_token')
	if carrinho_owner and carrinho_owner != cliente_token:
		request.session.pop('carrinho', None)
		request.session.pop('pedidos_ids', None)
		request.session.pop('ultimo_pedido_id', None)

	request.session['carrinho_owner_token'] = cliente_token
	request.session.modified = True

def index(request):
	return render(request, 'pizzaria/index.html')

def cardapio(request):
    pizzas = Pizza.objects.filter(disponivel=True)
    bebidas = Bebida.objects.filter(disponivel=True)
    return render(request, 'pizzaria/cardapio.html', {'pizzas': pizzas, 'bebidas': bebidas})

def contato(request):
	if request.method == 'POST':
		nome = request.POST.get('nome', '').strip()
		telefone = request.POST.get('telefone', '').strip()
		mensagem = request.POST.get('mensagem', '').strip()

		if len(nome) < 3:
			messages.error(request, 'Informe um nome valido.')
			return redirect('contato')

		telefone_numeros = re.sub(r'\D', '', telefone)
		if len(telefone_numeros) < 10 or len(telefone_numeros) > 11:
			messages.error(request, 'Informe um numero de telefone valido com DDD.')
			return redirect('contato')

		if not mensagem:
			messages.error(request, 'Digite uma mensagem.')
			return redirect('contato')

		texto = (
			f"Ola! Meu nome e {nome}.\n"
			f"Telefone: {telefone}\n\n"
			f"{mensagem}"
		)
		return redirect(f"https://wa.me/5584920031436?text={quote(texto)}")
	return render(request, 'pizzaria/contato.html')

# Escolher sabores
def escolher_sabores(request):
	pizzas = Pizza.objects.filter(disponivel=True)
	bebidas = Bebida.objects.filter(disponivel=True)
	pizzas_json = json.dumps([{
		'id': p.id,
		'nome': p.nome,
		'ingredientes': p.ingredientes,
		'especial': p.especial
	} for p in pizzas])
	pizzas_especiais_json = json.dumps([p.id for p in pizzas if p.especial])
	return render(request, 'pizzaria/escolher_sabores.html', {
		'pizzas_json': pizzas_json,
		'pizzas_especiais_json': pizzas_especiais_json,
		'bebidas': bebidas,
		'precos_json': precos_para_javascript(),
	})

# Carrinho views
def carrinho_adicionar(request, pizza_id):
	_ensure_cart_device_owner(request)
	carrinho = Carrinho(request)
	pizza = get_object_or_404(Pizza, id=pizza_id)
	carrinho.adicionar(pizza=pizza, quantidade=1)
	return redirect('carrinho_detalhes')

def carrinho_adicionar_pizza(request):
	if request.method == 'POST':
		_ensure_cart_device_owner(request)
		carrinho = Carrinho(request)
		quer_bebida = request.POST.get('quer_bebida')
		bebida_ids = request.POST.getlist('bebida_id[]')

		if quer_bebida == 'sim':
			for bebida_id in bebida_ids:
				if bebida_id:
					bebida = get_object_or_404(Bebida, id=bebida_id, disponivel=True)
					carrinho.adicionar(bebida=bebida, quantidade=1, preco=float(bebida.preco))

		# pizza flow
		tamanho = request.POST.get('tamanho')
		if tamanho not in {'P', 'M', 'G'}:
			messages.error(request, 'Selecione um tamanho válido.')
			return redirect('escolher_sabores')
		try:
			num_sabores = int(request.POST.get('num_sabores', 1))
		except (TypeError, ValueError):
			messages.error(request, 'Selecione entre 1 e 3 sabores.')
			return redirect('escolher_sabores')
		if num_sabores not in {1, 2, 3}:
			messages.error(request, 'Selecione entre 1 e 3 sabores.')
			return redirect('escolher_sabores')
		borda_chocolate = request.POST.get('borda_chocolate') == 'on'
		catupiry_cima = request.POST.get('catupiry_cima', 'nao')
		catupiry_borda = request.POST.get('catupiry_borda') == 'on'
		borda_tipo = request.POST.get('borda_tipo', 'catupiry')
		if borda_tipo not in {'catupiry', 'cheddar', 'sem_borda', 'catupiry_original', 'chocolate'}:
			borda_tipo = 'catupiry'
		# Mantém os campos antigos coerentes com a borda escolhida.
		if borda_tipo == 'chocolate':
			borda_chocolate = True
		elif borda_tipo == 'catupiry_original':
			catupiry_borda = True
		
		# Coletar sabores

		observacao = request.POST.get('observacao', '').strip()
		sabores_ids = []
		sabores_nomes = []
		sabores_especiais_count = 0
		
		for i in range(1, num_sabores + 1):
			sabor_id = request.POST.get(f'sabor_{i}')
			if sabor_id:
				pizza = get_object_or_404(Pizza, id=sabor_id, disponivel=True)
				sabores_ids.append(int(sabor_id))
				sabores_nomes.append(pizza.nome)
				if pizza.especial:
					sabores_especiais_count += 1
		if len(sabores_ids) != num_sabores:
			messages.error(request, 'Selecione todos os sabores da pizza.')
			return redirect('escolher_sabores')
		
		# Calcular preço
		preco_final = calcular_preco_pizza(
			tamanho=tamanho,
			sabores_especiais_count=sabores_especiais_count,
			total_sabores=num_sabores,
			borda_chocolate=borda_chocolate,
			catupiry_cima=catupiry_cima,
			catupiry_borda=catupiry_borda,
			borda_tipo=borda_tipo
		)
		
		# Criar descrição
		nomes_tamanho = {'P': 'Pequena', 'M': 'Média', 'G': 'Grande'}
		descricao = f"{nomes_tamanho[tamanho]} - {' / '.join(sabores_nomes)}"
		
		# Pizza principal (primeira selecionada)
		pizza_principal = get_object_or_404(Pizza, id=sabores_ids[0])
		
		# Adiciona ao carrinho
		carrinho.adicionar(
			pizza=pizza_principal,
			quantidade=1,
			preco=float(preco_final),
			tamanho=tamanho,
			borda_chocolate=borda_chocolate,
			catupiry_cima=catupiry_cima,
			catupiry_borda=catupiry_borda,
			borda_tipo=borda_tipo,
			observacao=observacao,
			sabores=json.dumps({
				'num_sabores': num_sabores,
				'ids': sabores_ids,
				'nomes': sabores_nomes,
				'descricao': descricao
			})
		)
		
		return redirect('carrinho_detalhes')
	return redirect('escolher_sabores')

@require_POST
def carrinho_remover(request, item_id):
	_ensure_cart_device_owner(request)
	carrinho = Carrinho(request)
	adicional = request.POST.get('adicional')
	if adicional:
		carrinho.remover_adicional(item_id, adicional)
	else:
		carrinho.remover(item_id)
	return redirect('carrinho_detalhes')

def carrinho_detalhes(request):
	_ensure_cart_device_owner(request)
	carrinho = Carrinho(request)
	from .models import TaxaEntrega
	cliente_token = request.session.get('cliente_token')
	pedidos_em_andamento = []
	if cliente_token:
		pedidos_em_andamento = list(
			Pedido.objects.filter(cliente_token=cliente_token)
			.exclude(status__in=['Pago', 'Entregue'])
			.prefetch_related('itens__pizza', 'itens__bebida')
			.order_by('-criado_em')
		)
		for pedido in pedidos_em_andamento:
			for item in pedido.itens.all():
				item.sabores_nomes = []
				if item.sabores:
					try:
						item.sabores_nomes = json.loads(unescape(item.sabores)).get('nomes', [])
					except (TypeError, ValueError):
						pass
	
	# Ordem personalizada dos locais
	ordem_locais = [
		'Lucrécia',
		'Lucrécia (Sitio)',
		'Três Altos',
		'Fogueteiro',
		'Logradouro',
		'Baixio de Onça',
		'Frutuoso Gomes',
		'Almino Afonso',
	]
	
	# Buscar taxas ativas e ordenar manualmente
	taxas_dict = {taxa.nome: taxa for taxa in TaxaEntrega.objects.filter(ativo=True)}
	taxas_entrega = [taxas_dict[nome] for nome in ordem_locais if nome in taxas_dict]
	
	# Processar sabores para o template
	itens_processados = []
	configuracao = ConfiguracaoPreco.obter()
	for item in carrinho:
		tamanho = item.get('tamanho', 'G')
		borda_tipo = resolver_borda_tipo(item)
		borda_valor = valor_borda(tamanho, borda_tipo, configuracao)
		catupiry_cima = item.get('catupiry_cima', 'nao')
		catupiry_cima_valor = valor_catupiry_cima(tamanho, catupiry_cima, configuracao)
		item_data = {
			'tipo': item.get('tipo', 'pizza'),
			'pizza': item.get('pizza'),
			'bebida': item.get('bebida'),
			'quantidade': item['quantidade'],
			'preco': item['preco'],
			'total': item['total'],
			'item_id': item['item_id'],
			'tamanho': item.get('tamanho', 'G'),
			'borda_chocolate': item.get('borda_chocolate', False),
			'catupiry_cima': item.get('catupiry_cima', 'nao'),
			'catupiry_borda': item.get('catupiry_borda', False),
			'borda_tipo': borda_tipo,
			'borda_label': rotulo_borda(borda_tipo),
			'borda_valor': borda_valor,
			'borda_valor_fmt': formatar_moeda(borda_valor),
			'catupiry_cima_valor': catupiry_cima_valor,
			'catupiry_cima_valor_fmt': formatar_moeda(catupiry_cima_valor),
			'observacao': item.get('observacao', ''),
			'tem_adicionais': (
				item.get('tipo', 'pizza') != 'bebida'
				and (
					borda_tipo != 'catupiry'
					or catupiry_cima != 'nao'
					or item.get('borda_chocolate', False)
					or item.get('catupiry_borda', False)
				)
			),
			'sabores_data': None
		}
		if item.get('sabores'):
			try:
				item_data['sabores_data'] = json.loads(unescape(item['sabores']))
			except:
				pass
		itens_processados.append(item_data)
	
	return render(request, 'pizzaria/carrinho.html', {
		'carrinho': carrinho,
		'itens': itens_processados,
		'taxas_entrega': taxas_entrega,
		'pedidos_em_andamento': pedidos_em_andamento,
	})

@require_POST
def carrinho_finalizar(request):
	_ensure_cart_device_owner(request)
	carrinho = Carrinho(request)
	if len(carrinho) == 0:
		return redirect('cardapio')
	
	# Obter dados do formulário
	nome = request.POST.get('nome', '').strip()
	endereco = request.POST.get('endereco', '').strip()
	observacoes = request.POST.get('observacoes', '').strip()
	pagamento = request.POST.get('pagamento', '').strip()
	troco = request.POST.get('troco', '').strip()
	local_entrega_id = request.POST.get('local_entrega', '')

	if len(nome) < 3:
		messages.error(request, 'Informe um nome válido para finalizar o pedido.')
		return redirect('carrinho_detalhes')

	pagamentos_validos = {'Dinheiro', 'PIX', 'Cartão na entrega'}
	if pagamento not in pagamentos_validos:
		messages.error(request, 'Selecione uma forma de pagamento válida.')
		return redirect('carrinho_detalhes')

	if not local_entrega_id:
		messages.error(request, 'Selecione o local de entrega.')
		return redirect('carrinho_detalhes')
	
	# Calcular taxa de entrega
	from .models import TaxaEntrega
	taxa_entrega = 0
	local_entrega = None
	nome_local = 'Retirada no local'
	
	if local_entrega_id != 'local':
		if not endereco:
			messages.error(request, 'Informe o endereço de entrega.')
			return redirect('carrinho_detalhes')
		try:
			local_entrega = TaxaEntrega.objects.get(id=local_entrega_id, ativo=True)
			taxa_entrega = local_entrega.taxa
			nome_local = local_entrega.nome
		except TaxaEntrega.DoesNotExist:
			messages.error(request, 'Local de entrega inválido. Selecione novamente.')
			return redirect('carrinho_detalhes')
	
	subtotal = carrinho.get_total()
	total_final = subtotal + taxa_entrega

	data_pedido = timezone.localdate()

	numero_do_dia = gerar_numero_pedido_diario(data_pedido)

	print("NÚMERO GERADO:", numero_do_dia)
	
	# Criar pedido no banco de dados
	pedido = Pedido.objects.create(
		cliente=nome,
		cliente_token=request.session.get('cliente_token', ''),
		endereco=endereco,
		observacao=observacoes,
		forma_pagamento=pagamento,
		troco=troco,
		local_entrega=local_entrega,
		taxa_entrega=taxa_entrega,
		subtotal=subtotal,
		total=total_final,
		status='Em andamento',
		data_pedido=data_pedido,
    	numero_do_dia=numero_do_dia,
	)
	
	# Criar itens do pedido
	for item in carrinho:
		item_tipo = item.get('tipo', 'pizza')
		ItemPedido.objects.create(
			pedido=pedido,
			item_tipo=item_tipo,
			pizza=item['pizza'] if item_tipo == 'pizza' else None,
			bebida=item['bebida'] if item_tipo == 'bebida' else None,
			quantidade=item['quantidade'],
			preco_unitario=item['preco'],
			observacao=item.get('observacao', ''),
			sabores=item.get('sabores'),
			tamanho=item.get('tamanho', 'G'),
			borda_chocolate=item.get('borda_chocolate', False),
			catupiry_cima=item.get('catupiry_cima', 'nao'),
			catupiry_borda=item.get('catupiry_borda', False),
			borda_tipo=resolver_borda_tipo(item)
		)
	
	# Limpar carrinho após finalizar
	carrinho.limpar()
	request.session['ultimo_pedido_id'] = pedido.id
	ids_pedidos = request.session.get('pedidos_ids', [])
	if pedido.id not in ids_pedidos:
		ids_pedidos.append(pedido.id)
	request.session['pedidos_ids'] = ids_pedidos
	request.session.modified = True
	return redirect('carrinho_detalhes')

@dono_required
def painel(request):
	from django.db.models import Sum, Count, Q
	
	hoje = timezone.localdate()

	data_inicio_filtro = request.GET.get('data_inicio', '').strip()
	data_fim_filtro = request.GET.get('data_fim', '').strip()
	data_inicio_periodo = None
	data_fim_periodo = None
	filtro_data_erro = False

	try:
		if data_inicio_filtro:
			data_inicio_periodo = date_type.fromisoformat(data_inicio_filtro)
		if data_fim_filtro:
			data_fim_periodo = date_type.fromisoformat(data_fim_filtro)
		if data_inicio_periodo and data_fim_periodo and data_inicio_periodo > data_fim_periodo:
			raise ValueError
	except ValueError:
		filtro_data_erro = True
		data_inicio_periodo = None
		data_fim_periodo = None
		messages.error(request, 'Informe um intervalo de datas válido.')
	
	def inicio_do_dia(data):
		return timezone.make_aware(datetime.combine(data, datetime.min.time()))

	pedidos_periodo = Pedido.objects.all()
	if data_inicio_periodo:
		pedidos_periodo = pedidos_periodo.filter(criado_em__gte=inicio_do_dia(data_inicio_periodo))
	if data_fim_periodo:
		pedidos_periodo = pedidos_periodo.filter(
			criado_em__lt=inicio_do_dia(data_fim_periodo + timedelta(days=1))
		)
	faturamento_periodo = pedidos_periodo.aggregate(total=Sum('total'))['total'] or 0
	
	inicio_hoje = inicio_do_dia(hoje)
	inicio_ontem = inicio_do_dia(hoje - timedelta(days=1))
	inicio_semana = inicio_do_dia(hoje - timedelta(days=7))
	inicio_mes = inicio_do_dia(hoje - timedelta(days=30))
	
	# Contadores básicos
	pizzas_total = Pizza.objects.count()
	pedidos_hoje = Pedido.objects.filter(criado_em__gte=inicio_hoje, criado_em__lt=inicio_hoje + timedelta(days=1)).count()
	pedidos_novos = Pedido.objects.filter(status='Novo').count()
	
	# Faturamento
	faturamento_hoje = Pedido.objects.filter(criado_em__gte=inicio_hoje, criado_em__lt=inicio_hoje + timedelta(days=1)).aggregate(total=Sum('total'))['total'] or 0
	
	faturamento_semana = Pedido.objects.filter(criado_em__gte=inicio_semana).aggregate(total=Sum('total'))['total'] or 0
	
	faturamento_mes = Pedido.objects.filter(criado_em__gte=inicio_mes).aggregate(total=Sum('total'))['total'] or 0
	faturamento_bruto = Pedido.objects.aggregate(total=Sum('total'))['total'] or 0

	# Série diária usada pelo gráfico de vendas do dashboard
	primeiro_pedido = Pedido.objects.order_by('criado_em').values_list('criado_em', flat=True).first()
	data_inicial_grafico = timezone.localtime(primeiro_pedido).date() if primeiro_pedido else hoje
	grafico_vendas = []
	for dias_desde_inicio in range((hoje - data_inicial_grafico).days + 1):
		data = data_inicial_grafico + timedelta(days=dias_desde_inicio)
		inicio = inicio_do_dia(data)
		total_dia = Pedido.objects.filter(criado_em__gte=inicio, criado_em__lt=inicio + timedelta(days=1)).aggregate(total=Sum('total'))['total'] or 0
		grafico_vendas.append({
			'data': data.strftime('%d/%m'),
			'valor': float(total_dia),
		})
	
	# Ticket médio
	pedidos_totais = Pedido.objects.count()
	faturamento_total = Pedido.objects.aggregate(total=Sum('total'))['total'] or 0
	ticket_medio = faturamento_total / pedidos_totais if pedidos_totais > 0 else 0
	
	# Pizza mais vendida
	pizza_mais_vendida = ItemPedido.objects.values('pizza__nome').annotate(
		total=Sum('quantidade')
	).order_by('-total').first()
	
	# Tamanho mais vendido
	tamanho_mais_vendido = ItemPedido.objects.values('tamanho').annotate(
		total=Sum('quantidade')
	).order_by('-total').first()
	
	# Status dos pedidos
	status_pedidos = {
		'novos': Pedido.objects.filter(status='Novo').count(),
		'preparo': Pedido.objects.filter(status='Em preparo').count(),
		'prontos': Pedido.objects.filter(status='Pronto').count(),
		'pagos': Pedido.objects.filter(status='Pago').count(),
	}
	
	# Pedidos por período
	pedidos_ontem = Pedido.objects.filter(criado_em__gte=inicio_ontem, criado_em__lt=inicio_ontem + timedelta(days=1)).count()
	pedidos_semana = Pedido.objects.filter(criado_em__gte=inicio_semana).count()
	
	# Top 5 pizzas mais vendidas
	top_pizzas = ItemPedido.objects.values('pizza__nome').annotate(
		total=Sum('quantidade')
	).order_by('-total')[:5]


	# Puxa todos os motoqueiros para listar as opções no painel

	motoqueiros_lista = User.objects.filter(groups__name='Motoqueiros', is_active=True)
	
	context = {
		'active_page': 'dashboard',
		'pizzas_total': pizzas_total,
		'pedidos_hoje': pedidos_hoje,
		'pedidos_novos': pedidos_novos,
		'faturamento_hoje': faturamento_hoje,
		'faturamento_semana': faturamento_semana,
		'faturamento_mes': faturamento_mes,
		'faturamento_bruto': faturamento_bruto,
		'faturamento_periodo': faturamento_periodo,
		'pedidos_periodo': pedidos_periodo.count(),
		'data_inicio_filtro': data_inicio_filtro if not filtro_data_erro else '',
		'data_fim_filtro': data_fim_filtro if not filtro_data_erro else '',
		'filtro_data_ativo': bool(data_inicio_periodo or data_fim_periodo),
		'grafico_vendas': grafico_vendas,
		'ticket_medio': ticket_medio,
		'pizza_mais_vendida': pizza_mais_vendida,
		'tamanho_mais_vendido': tamanho_mais_vendido,
		'status_pedidos': status_pedidos,
		'pedidos_ontem': pedidos_ontem,
		'pedidos_semana': pedidos_semana,
		'top_pizzas': top_pizzas,
		'motoqueiros_disponiveis': motoqueiros_lista,
	}
	
	return render(request, 'pizzaria/painel.html', context)




@dono_required
def painel_pizzas(request):
	pizzas = Pizza.objects.all().order_by('-criado_em')
	return render(request, 'pizzaria/painel_pizzas.html', {'pizzas': pizzas, 'active_page': 'pizzas'})

@dono_required
def pizza_adicionar(request):
	if request.method == 'POST':
		nome = request.POST.get('nome')
		ingredientes = request.POST.get('ingredientes')
		especial = request.POST.get('especial') == 'on'
		categoria = 'doce' if request.POST.get('doce') == 'on' else 'salgada'
		imagem = request.FILES.get('imagem')
		Pizza.objects.create(nome=nome, ingredientes=ingredientes, especial=especial, categoria=categoria, imagem=imagem)
		return redirect('painel_pizzas')
	return render(request, 'pizzaria/pizza_form.html', {'active_page': 'pizzas'})

@dono_required
def pizza_editar(request, pizza_id):
	pizza = get_object_or_404(Pizza, id=pizza_id)
	if request.method == 'POST':
		pizza.nome = request.POST.get('nome')
		pizza.ingredientes = request.POST.get('ingredientes')
		pizza.especial = request.POST.get('especial') == 'on'
		pizza.categoria = 'doce' if request.POST.get('doce') == 'on' else 'salgada'
		pizza.disponivel = request.POST.get('disponivel') == 'on'
		if request.FILES.get('imagem'):
			pizza.imagem = request.FILES['imagem']
		pizza.save()
		return redirect('painel_pizzas')
	return render(request, 'pizzaria/pizza_form.html', {'pizza': pizza, 'active_page': 'pizzas'})

@dono_required
@require_POST
def pizza_excluir(request, pizza_id):
	pizza = get_object_or_404(Pizza, id=pizza_id)
	pizza.delete()
	return redirect('painel_pizzas')

# Gerenciar Bebidas
@dono_required
def painel_bebidas(request):
	bebidas = Bebida.objects.all().order_by('nome')
	return render(request, 'pizzaria/painel_bebidas.html', {'bebidas': bebidas, 'active_page': 'bebidas'})

@dono_required
def configurar_precos(request):
    configuracao = ConfiguracaoPreco.obter()

    grupos = [
        ('Preços base das pizzas', 'preco'),
        ('Pizza especial — parte dos sabores', 'especial_parcial'),
        ('Pizza especial — todos os sabores', 'especial_total'),
        ('Borda de Catupiry', 'borda_catupiry'),
        ('Borda de Cheddar', 'borda_cheddar'),
        ('Borda de Catupiry Original', 'borda_catupiry_original'),
        ('Borda de Chocolate', 'borda_chocolate'),
        ('Catupiry por cima — metade', 'catupiry_cima_metade'),
        ('Catupiry por cima — inteira', 'catupiry_cima_inteira'),
    ]
    tamanhos = [('p', 'Pequena'), ('m', 'Média'), ('g', 'Grande')]

    campos = [
        f'{prefixo}_{tamanho}'
        for _, prefixo in grupos
        for tamanho, _ in tamanhos
    ]

    if request.method == 'POST':
        for campo in campos:
            valor = request.POST.get(campo, '0').strip().replace(',', '.')
            setattr(configuracao, campo, valor or '0')

        try:
            configuracao.full_clean()
            configuracao.save()
            messages.success(request, 'Preços atualizados com sucesso!')
            return redirect('configurar_precos')
        except ValidationError:
            messages.error(
                request,
                'Verifique os valores informados. Use apenas números iguais ou maiores que zero.',
            )

    grupos_template = []
    for titulo, prefixo in grupos:
        grupos_template.append({
            'titulo': titulo,
            'campos': [
                {
                    'nome': f'{prefixo}_{tamanho}',
                    'rotulo': rotulo,
                    'valor': getattr(configuracao, f'{prefixo}_{tamanho}'),
                }
                for tamanho, rotulo in tamanhos
            ],
        })

    return render(request, 'pizzaria/precos.html', {
        'grupos_preco': grupos_template,
        'active_page': 'precos',
    })

@dono_required
def bebida_adicionar(request):
	if request.method == 'POST':
		nome = request.POST.get('nome', '').strip()
		descricao = request.POST.get('descricao', '').strip()
		preco = request.POST.get('preco', '0')
		disponivel = request.POST.get('disponivel') == 'on'
		imagem = request.FILES.get('imagem')
		Bebida.objects.create(nome=nome, descricao=descricao, imagem=imagem, preco=preco, disponivel=disponivel)
		return redirect('painel_bebidas')
	return render(request, 'pizzaria/bebida_form.html', {'active_page': 'bebidas'})

@dono_required
def bebida_editar(request, bebida_id):
	bebida = get_object_or_404(Bebida, id=bebida_id)
	if request.method == 'POST':
		bebida.nome = request.POST.get('nome', '').strip()
		bebida.descricao = request.POST.get('descricao', '').strip()
		bebida.preco = request.POST.get('preco', '0')
		bebida.disponivel = request.POST.get('disponivel') == 'on'
		if request.FILES.get('imagem'):
			bebida.imagem = request.FILES['imagem']
		bebida.save()
		return redirect('painel_bebidas')
	return render(request, 'pizzaria/bebida_form.html', {'bebida': bebida, 'active_page': 'bebidas'})

@dono_required
@require_POST
def bebida_excluir(request, bebida_id):
	bebida = get_object_or_404(Bebida, id=bebida_id)
	bebida.delete()
	return redirect('painel_bebidas')

# Gerenciar Pedidos
def _contexto_painel_pedidos(request):
	filtro = request.GET.get('filtro', 'hoje')
	data_especifica = request.GET.get('data', '')

	def pedidos_do_dia(queryset, data):
		inicio = timezone.make_aware(datetime.combine(data, datetime.min.time()))
		fim = inicio + timedelta(days=1)
		return queryset.filter(
			Q(criado_em__gte=inicio, criado_em__lt=fim) |
			Q(reaberto_em__gte=inicio, reaberto_em__lt=fim)
		)

	if garcom_user(request.user):
		base_pedidos = Pedido.objects.filter(usuario=request.user)
	else:
		base_pedidos = Pedido.objects.all()
	base_pedidos = base_pedidos.select_related('usuario', 'local_entrega')

	if data_especifica:
		try:
			data_obj = datetime.strptime(data_especifica, '%Y-%m-%d').date()
			pedidos = pedidos_do_dia(base_pedidos, data_obj)
			filtro = 'data'
		except ValueError:
			data_especifica = ''
			pedidos = pedidos_do_dia(base_pedidos, timezone.localdate())
	else:
		# Filtrar por data padrão
		hoje = timezone.localdate()
		if filtro == 'hoje':
			pedidos = pedidos_do_dia(base_pedidos, hoje)
		elif filtro == 'ontem':
			ontem = hoje - timedelta(days=1)
			pedidos = pedidos_do_dia(base_pedidos, ontem)
		elif filtro == '7dias':
			sete_dias_atras = hoje - timedelta(days=7)
			inicio = timezone.make_aware(datetime.combine(sete_dias_atras, datetime.min.time()))
			pedidos = base_pedidos.filter(
				Q(criado_em__gte=inicio) | Q(reaberto_em__gte=inicio)
			)
		else:  # todos
			pedidos = base_pedidos
	
	pedidos = pedidos.exclude(status='Pago').order_by('-criado_em')
	
	# Processar sabores para cada pedido (seu código original)
	pedidos_processados = []
	for pedido in pedidos:
		itens_processados = []
		for item in pedido.itens.all():
			item_data = {
				'item': item,
				'sabores_lista': None
			}
			if item.sabores:
				try:
					sabores_data = json.loads(unescape(item.sabores))
					nomes = sabores_data.get('nomes', [])
					item_data['sabores_lista'] = ', '.join(nomes)
				except:
					pass
			itens_processados.append(item_data)
		pedido.itens_processados = itens_processados
		pedido.cadastrado_por_garcom = bool(
			pedido.usuario and pedido.usuario.groups.filter(name='Garçons').exists()
		)
		pedidos_processados.append(pedido)

	motoqueiros_lista = User.objects.filter(groups__name='Motoqueiros', is_active=True).order_by('first_name')
	
	return {
		'pedidos': pedidos_processados,
		'active_page': 'pedidos',
		'filtro_atual': filtro,
		'data_filtro': data_especifica,
		'motoqueiros_lista': motoqueiros_lista,
	}

@login_required(login_url='/login/')
def painel_pedidos(request):
	return render(request, 'pizzaria/painel_pedidos.html', _contexto_painel_pedidos(request))

@login_required(login_url='/login/')
@require_GET
def painel_pedidos_lista(request):
	"""Partial HTML com apenas os cards de pedidos, consumido pelo polling do HTMX."""
	return render(request, 'pizzaria/partials/painel_pedidos_lista.html', _contexto_painel_pedidos(request))

def _contexto_historico_pedidos(request):
	data_filtro = request.GET.get('data', '')
	pedidos = Pedido.objects.select_related('usuario', 'local_entrega').all()
	if data_filtro:
		try:
			data_obj = datetime.strptime(data_filtro, '%Y-%m-%d').date()
			pedidos = pedidos.filter(criado_em__date=data_obj)
		except ValueError:
			data_filtro = ''
	pedidos = pedidos.prefetch_related('itens__pizza', 'itens__bebida').order_by('-criado_em')
	for pedido in pedidos:
		pedido.cadastrado_por_garcom = bool(
			pedido.usuario and pedido.usuario.groups.filter(name='Garçons').exists()
		)
		for item in pedido.itens.all():
			item.sabores_nomes = []
			if item.sabores:
				try:
					item.sabores_nomes = json.loads(unescape(item.sabores)).get('nomes', [])
				except (TypeError, ValueError):
					pass
	return {
		'pedidos': pedidos,
		'data_filtro': data_filtro,
		'active_page': 'historico',
		'usuario_e_garcom': garcom_user(request.user),
	}

@login_required(login_url='/login/')
def historico_pedidos(request):
	return render(request, 'pizzaria/historico_pedidos.html', _contexto_historico_pedidos(request))

@login_required(login_url='/login/')
@require_GET
def historico_pedidos_lista(request):
	"""Partial HTML com apenas os cards do histórico, consumido pelo polling do HTMX."""
	return render(request, 'pizzaria/partials/historico_pedidos_lista.html', _contexto_historico_pedidos(request))

@dono_required
def painel_garcons(request):
	grupo, _ = Group.objects.get_or_create(name='Garçons')
	garcons = User.objects.filter(groups=grupo).order_by('-is_active', 'first_name', 'username')
	return render(request, 'pizzaria/painel_garcons.html', {
		'garcons': garcons,
		'active_page': 'garcons',
	})

@dono_required
@require_POST
def garcom_deletar_permanente(request, user_id):
	garcom = get_object_or_404(User, id=user_id, groups__name='Garçons')
	nome_garcom = garcom.get_full_name() or garcom.username
	garcom.delete()
	messages.success(request, f"O garçom {nome_garcom} foi excluído permanentemente.")
	return redirect('painel_garcons')

@dono_required
@require_POST
def garcom_ativar(request, user_id):
	garcom = get_object_or_404(User, id=user_id, groups__name='Garçons')
	garcom.is_active = True
	garcom.save(update_fields=['is_active'])
	messages.success(request, 'Garçom reativado com sucesso.')
	return redirect('painel_garcons')

@dono_required
@require_POST
def garcom_adicionar(request):
	nome = request.POST.get('nome', '').strip()
	senha = request.POST.get('senha', '')
	if len(nome) < 2:
		messages.error(request, 'Informe o nome do garçom.')
		return redirect('painel_garcons')
	if len(senha) < 6:
		messages.error(request, 'A senha deve ter pelo menos 6 caracteres.')
		return redirect('painel_garcons')
	if User.objects.filter(username__iexact=nome).exists():
		messages.error(request, 'Já existe um usuário com esse nome.')
		return redirect('painel_garcons')

	garcom = User.objects.create_user(username=nome, first_name=nome, password=senha)
	grupo, _ = Group.objects.get_or_create(name='Garçons')
	garcom.groups.add(grupo)
	messages.success(request, f'Garçom {nome} cadastrado com sucesso.')
	return redirect('painel_garcons')

@dono_required
@require_POST
def garcom_excluir(request, user_id):
	garcom = get_object_or_404(User, id=user_id, groups__name='Garçons')
	garcom.is_active = False
	garcom.save(update_fields=['is_active'])
	messages.success(request, 'Garçom desativado com sucesso.')
	return redirect('painel_garcons')

@login_required(login_url='/login/')
@require_POST
def pedido_reabrir(request, pedido_id):
	pedido = get_object_or_404(Pedido, id=pedido_id)
	novo_status = request.POST.get('status', '').strip()
	status_reabertura = {valor for valor, _ in Pedido.STATUS_CHOICES if valor != 'Pago'}
	if novo_status in status_reabertura:
		pedido.status = novo_status
		pedido.reaberto_em = timezone.now()
		pedido.save(update_fields=['status', 'reaberto_em', 'atualizado_em'])
	else:
		messages.error(request, 'Escolha um status válido para reabrir o pedido.')
	return redirect('historico_pedidos')

def _criar_itens_pedido(request, pedido):
	"""Cria os itens (pizzas e bebidas) do POST e devolve o subtotal."""
	sabores_1_ids = request.POST.getlist('sabor_1[]')
	# Compatibilidade com versoes antigas do formulario
	if not sabores_1_ids:
		sabores_1_ids = request.POST.getlist('pizza_id[]')
	numeros_sabores = request.POST.getlist('num_sabores[]')
	sabores_2_ids = request.POST.getlist('sabor_2[]')
	sabores_3_ids = request.POST.getlist('sabor_3[]')
	quantidades = request.POST.getlist('quantidade[]')
	tamanhos = request.POST.getlist('tamanho[]')
	bordas_chocolate = request.POST.getlist('borda_chocolate[]')
	bordas_tipo = request.POST.getlist('borda_tipo[]')
	catupiry_cima_lista = request.POST.getlist('catupiry_cima[]')
	catupiry_borda_lista = request.POST.getlist('catupiry_borda[]')
	observacoes_itens = request.POST.getlist('observacao_item[]')
	bebidas_ids = request.POST.getlist('bebida_id[]')
	bebidas_quantidades = request.POST.getlist('bebida_quantidade[]')

	def valor_da_lista(lista, indice, padrao=''):
		return lista[indice] if indice < len(lista) else padrao
	
	total = 0
	for i, sabor_1_id in enumerate(sabores_1_ids):
		if not sabor_1_id or not str(sabor_1_id).isdigit():
			continue

		quantidade_raw = valor_da_lista(quantidades, i, '1')
		tamanho = valor_da_lista(tamanhos, i, 'G')
		if tamanho not in {'P', 'M', 'G'}:
			tamanho = 'G'
		borda_chocolate = valor_da_lista(bordas_chocolate, i) in {'sim', 'on', '1'}
		borda_tipo = valor_da_lista(bordas_tipo, i, 'catupiry')
		if borda_tipo == 'catupiry' and valor_da_lista(bordas_chocolate, i) in {'sim', 'on', '1'}:
			borda_tipo = 'chocolate'
		elif borda_tipo == 'catupiry' and valor_da_lista(catupiry_borda_lista, i) in {'sim', 'on', '1'}:
			borda_tipo = 'catupiry_original'
		if borda_tipo not in {'catupiry', 'cheddar', 'sem_borda', 'catupiry_original', 'chocolate'}:
			borda_tipo = 'catupiry'
		if borda_tipo in {'chocolate', 'catupiry_original'}:
			borda_chocolate = borda_tipo == 'chocolate'
		catupiry_cima = valor_da_lista(catupiry_cima_lista, i, 'nao')
		if catupiry_cima not in {'nao', 'metade', 'inteira'}:
			catupiry_cima = 'nao'
		catupiry_borda = valor_da_lista(catupiry_borda_lista, i) in {'sim', 'on', '1'}
		if borda_chocolate:
			catupiry_borda = False

		try:
			quantidade = max(1, int(quantidade_raw))
		except ValueError:
			quantidade = 1

		observacao_item = valor_da_lista(observacoes_itens, i).strip()

		try:
			num_sabores = int(valor_da_lista(numeros_sabores, i, '1'))
		except ValueError:
			num_sabores = 1
		num_sabores = max(1, min(3, num_sabores))

		sabores_escolhidos = []
		pizza_1 = get_object_or_404(Pizza, id=sabor_1_id)
		sabores_escolhidos.append(pizza_1)

		sabor_2_id = valor_da_lista(sabores_2_ids, i)
		if num_sabores >= 2 and str(sabor_2_id).isdigit():
			sabores_escolhidos.append(get_object_or_404(Pizza, id=sabor_2_id))

		sabor_3_id = valor_da_lista(sabores_3_ids, i)
		if num_sabores >= 3 and str(sabor_3_id).isdigit():
			sabores_escolhidos.append(get_object_or_404(Pizza, id=sabor_3_id))

		total_sabores = len(sabores_escolhidos)
		sabores_especiais_count = sum(1 for sabor in sabores_escolhidos if sabor.especial)

		preco_unitario = calcular_preco_pizza(
			tamanho=tamanho,
			sabores_especiais_count=sabores_especiais_count,
			total_sabores=total_sabores,
			borda_chocolate=borda_chocolate,
			catupiry_cima=catupiry_cima,
			catupiry_borda=catupiry_borda
			,borda_tipo=borda_tipo
		)

		sabores_json = None
		if total_sabores > 1:
			nomes_tamanho = {'P': 'Pequena', 'M': 'Média', 'G': 'Grande'}
			nomes = [sabor.nome for sabor in sabores_escolhidos]
			sabores_json = json.dumps({
				'num_sabores': total_sabores,
				'ids': [sabor.id for sabor in sabores_escolhidos],
				'nomes': nomes,
				'descricao': f"{nomes_tamanho[tamanho]} - {' / '.join(nomes)}"
			})

		ItemPedido.objects.create(
			pedido=pedido,
			item_tipo='pizza',
			pizza=sabores_escolhidos[0],
			quantidade=quantidade,
			preco_unitario=preco_unitario,
			tamanho=tamanho,
			sabores=sabores_json,
			borda_chocolate=borda_chocolate,
			catupiry_cima=catupiry_cima,
			catupiry_borda=catupiry_borda,
			borda_tipo=borda_tipo,
			observacao=observacao_item,
		)
		total += preco_unitario * quantidade

	for i, bebida_id in enumerate(bebidas_ids):
		if not bebida_id or not str(bebida_id).isdigit():
			continue

		bebida = get_object_or_404(Bebida, id=bebida_id, disponivel=True)
		quantidade_raw = valor_da_lista(bebidas_quantidades, i, '1')
		try:
			quantidade = max(1, int(quantidade_raw))
		except ValueError:
			quantidade = 1

		ItemPedido.objects.create(
			pedido=pedido,
			item_tipo='bebida',
			bebida=bebida,
			quantidade=quantidade,
			preco_unitario=bebida.preco
		)
		total += bebida.preco * quantidade
	return total

@login_required(login_url='/login/')
def pedido_adicionar(request):
	if request.method == 'POST':
		cliente = request.POST.get('cliente', '').strip()
		telefone = request.POST.get('telefone', '').strip()
		endereco = request.POST.get('endereco', '').strip()
		observacao = request.POST.get('observacao', '').strip()
		local_entrega_id = request.POST.get('local_entrega', '')
		if garcom_user(request.user):
			local_entrega_id = 'local'
		forma_pagamento = request.POST.get('forma_pagamento', '').strip()
		troco = request.POST.get('troco', '').strip()

		pagamentos_validos = {'Dinheiro', 'PIX', 'Cartão na entrega'}
		if not garcom_user(request.user) and forma_pagamento not in pagamentos_validos:
			messages.error(request, 'Selecione uma forma de pagamento válida.')
			return redirect('pedido_adicionar')
		if garcom_user(request.user) and forma_pagamento and forma_pagamento not in pagamentos_validos:
			messages.error(request, 'Selecione uma forma de pagamento válida.')
			return redirect('pedido_adicionar')
		if not local_entrega_id:
			messages.error(request, 'Selecione o local de entrega.')
			return redirect('pedido_adicionar')

		local_entrega = None
		taxa_entrega = 0
		if local_entrega_id != 'local':
			if not endereco and not garcom_user(request.user):
				messages.error(request, 'Informe o endereço de entrega.')
				return redirect('pedido_adicionar')
			try:
				local_entrega = TaxaEntrega.objects.get(id=local_entrega_id, ativo=True)
				taxa_entrega = local_entrega.taxa
			except (TaxaEntrega.DoesNotExist, ValueError):
				messages.error(request, 'Local de entrega inválido. Selecione novamente.')
				return redirect('pedido_adicionar')


		data_pedido = timezone.localdate()
		numero_do_dia = gerar_numero_pedido_diario(data_pedido)

		pedido = Pedido.objects.create(
			usuario=request.user,
			cliente=cliente,
			telefone=telefone,
			endereco=endereco,
			observacao=observacao,
			forma_pagamento=forma_pagamento,
			troco=troco,
			local_entrega=local_entrega,
			taxa_entrega=taxa_entrega,
			total=0,
			data_pedido=data_pedido,
    		numero_do_dia=numero_do_dia
		)
		
		total = _criar_itens_pedido(request, pedido)
		
		pedido.subtotal = total
		pedido.total = total + taxa_entrega
		pedido.save()
		return redirect('painel_pedidos')
	
	pizzas = Pizza.objects.filter(disponivel=True)
	bebidas = Bebida.objects.filter(disponivel=True)
	ordem_locais = [
		'Lucrécia',
		'Lucrécia (Sitio)',
		'Três Altos',
		'Fogueteiro',
		'Logradouro',
		'Baixio de Onça',
		'Frutuoso Gomes',
		'Almino Afonso',
	]
	taxas_dict = {taxa.nome: taxa for taxa in TaxaEntrega.objects.filter(ativo=True)}
	taxas_entrega = [taxas_dict[nome] for nome in ordem_locais if nome in taxas_dict]
	return render(request, 'pizzaria/pedido_form.html', {
		'pizzas': pizzas,
		'bebidas': bebidas,
		'taxas_entrega': taxas_entrega,
		'usuario_e_garcom': garcom_user(request.user),
		'active_page': 'pedidos',
		'precos_json': precos_para_javascript(),
	})

@login_required(login_url='/login/')
@require_POST
@csrf_exempt
def pedido_alterar_status(request, pedido_id):
	pedido = get_object_or_404(Pedido, id=pedido_id)
	novo_status = request.POST.get('status')
	motoqueiro_id = request.POST.get('motoqueiro_id')

	# Só altera o entregador se o campo foi enviado no formulário
	if motoqueiro_id is not None:
		if motoqueiro_id.isdigit():
			motoqueiro_user = get_object_or_404(User, id=int(motoqueiro_id), groups__name='Motoqueiros')
			pedido.motoqueiro = motoqueiro_user
		elif motoqueiro_id == "": 
			pedido.motoqueiro = None

	# Validação e gravação do status do pedido
	status_validos = {valor for valor, _ in Pedido.STATUS_CHOICES}
	if novo_status in status_validos:
		pedido.status = novo_status
		if novo_status == 'Pago':
			pedido.fechado_em = timezone.now()
		
		# Salva todas as alterações juntas (Status e Entregador) de forma persistente
		pedido.save()
		messages.success(request, 'Pedido atualizado com sucesso!')
	else:
		messages.error(request, 'Status inválido para o pedido.')
		
	return redirect('painel_pedidos')

def _descricao_item_pedido(item):
	"""Nome legível do item para a tela de edição (sabores múltiplos incluídos)."""
	if item.item_tipo == 'bebida':
		return item.bebida.nome if item.bebida else 'Bebida'
	if item.sabores:
		try:
			nomes = json.loads(unescape(item.sabores)).get('nomes', [])
			if nomes:
				return 'Pizza: ' + ', '.join(nomes)
		except (TypeError, ValueError):
			pass
	return item.pizza.nome if item.pizza else 'Pizza'

@login_required(login_url='/login/')
def pedido_editar(request, pedido_id):
	"""Edita dados e itens de um pedido ativo (admin e gar?om) sem tocar no andamento dele.

	Status, entregador, número do dia, data de criação e responsável nunca são
	alterados aqui, e a gravação usa update_fields para não sobrescrever mudanças
	de status feitas em paralelo por outro usuário.
	"""
	e_garcom = garcom_user(request.user)
	pedidos = Pedido.objects.all()
	if e_garcom:
		pedidos = pedidos.filter(usuario=request.user)
	pedido = get_object_or_404(pedidos, id=pedido_id)

	if pedido.status == 'Pago':
		messages.error(request, 'Pedidos pagos não podem ser editados. Reabra o pedido pelo histórico.')
		return redirect('painel_pedidos')

	if request.method == 'POST':
		with transaction.atomic():
			pedido = get_object_or_404(pedidos.select_for_update(), id=pedido_id)
			if pedido.status == 'Pago':
				messages.error(request, 'Este pedido acabou de ser pago e não pode mais ser editado.')
				return redirect('painel_pedidos')

			erro = _aplicar_edicao_pedido(request, pedido)
			if erro:
				messages.error(request, erro)
				transaction.set_rollback(True)
				return redirect('pedido_editar', pedido_id=pedido.id)

		messages.success(request, f'Pedido #{pedido.id:03d} atualizado com sucesso!')
		return redirect('painel_pedidos')

	return _render_form_edicao_completa(request, pedido)

def _render_form_edicao_completa(request, pedido):
	"""Formulário de criação de pedido preenchido com os dados atuais (admin e gar?om)."""
	itens = list(pedido.itens.select_related('pizza', 'bebida').order_by('id'))
	pizzas_ids, bebidas_ids = set(), set()
	pizzas_dados, bebidas_dados = [], []
	for item in itens:
		if item.item_tipo == 'bebida':
			if item.bebida_id:
				bebidas_ids.add(item.bebida_id)
				bebidas_dados.append({'bebida': item.bebida_id, 'quantidade': item.quantidade})
			continue
		ids = [item.pizza_id] if item.pizza_id else []
		if item.sabores:
			try:
				ids = [int(i) for i in json.loads(unescape(item.sabores)).get('ids', [])] or ids
			except (TypeError, ValueError):
				pass
		pizzas_ids.update(ids)
		pizzas_dados.append({
			'sabores': ids,
			'tamanho': item.tamanho,
			'borda_tipo': item.borda_tipo,
			'catupiry_cima': item.catupiry_cima,
			'quantidade': item.quantidade,
			'observacao': unescape(item.observacao or ''),
		})

	ordem_locais = ['Lucrécia', 'Lucrécia (Sitio)', 'Três Altos', 'Fogueteiro', 'Logradouro',
		'Baixio de Onça', 'Frutuoso Gomes', 'Almino Afonso']
	taxas = list(TaxaEntrega.objects.filter(Q(ativo=True) | Q(id=pedido.local_entrega_id)))
	taxas.sort(key=lambda t: (ordem_locais.index(t.nome) if t.nome in ordem_locais else len(ordem_locais), t.nome))

	return render(request, 'pizzaria/pedido_form.html', {
		'edicao': True,
		'pedido': pedido,
		'cliente': unescape(pedido.cliente or ''),
		'telefone': unescape(pedido.telefone or ''),
		'endereco': unescape(pedido.endereco or ''),
		'observacao': unescape(pedido.observacao or ''),
		'troco': unescape(pedido.troco or ''),
		'edicao_itens': {'pizzas': pizzas_dados, 'bebidas': bebidas_dados},
		'pizzas': Pizza.objects.filter(Q(disponivel=True) | Q(id__in=pizzas_ids)),
		'bebidas': Bebida.objects.filter(Q(disponivel=True) | Q(id__in=bebidas_ids)),
		'taxas_entrega': taxas,
		'usuario_e_garcom': False,
		'active_page': 'pedidos',
		'precos_json': precos_para_javascript(),
	})

def _aplicar_edicao_pedido(request, pedido):
	"""Valida o POST e grava a edi??o completa. Retorna uma mensagem de erro ou None."""
	cliente = request.POST.get('cliente', '').strip()
	telefone = request.POST.get('telefone', '').strip()
	endereco = request.POST.get('endereco', '').strip()
	forma_pagamento = request.POST.get('forma_pagamento', '').strip()
	troco = request.POST.get('troco', '').strip()
	local_entrega_id = request.POST.get('local_entrega', '')

	if not cliente:
		return 'Informe o nome do cliente.'
	if forma_pagamento not in {'Dinheiro', 'PIX', 'Cart?o na entrega'}:
		return 'Selecione uma forma de pagamento v?lida.'
	if not local_entrega_id:
		return 'Selecione o local de entrega.'

	if local_entrega_id == 'local':
		pedido.local_entrega = None
		pedido.taxa_entrega = 0
	else:
		if not endereco:
			return 'Informe o endere?o de entrega.'
		if local_entrega_id != str(pedido.local_entrega_id):
			try:
				local = TaxaEntrega.objects.get(id=local_entrega_id, ativo=True)
			except (TaxaEntrega.DoesNotExist, ValueError):
				return 'Local de entrega inv?lido. Selecione novamente.'
			pedido.local_entrega = local
			pedido.taxa_entrega = local.taxa
		# Local inalterado: mant?m a taxa que foi cobrada no pedido original.

	pedido.cliente = cliente
	pedido.telefone = telefone
	pedido.endereco = endereco
	pedido.observacao = request.POST.get('observacao', '').strip()
	pedido.forma_pagamento = forma_pagamento
	pedido.troco = troco if forma_pagamento == 'Dinheiro' else ''

	# Os itens s?o refeitos a partir do formul?rio; a transa??o desfaz tudo se falhar.
	pedido.itens.all().delete()
	subtotal = _criar_itens_pedido(request, pedido)
	if not pedido.itens.exists():
		return 'O pedido precisa ter pelo menos um item.'
	pedido.subtotal = subtotal
	pedido.total = subtotal + pedido.taxa_entrega
	pedido.save(update_fields=[
		'cliente', 'telefone', 'endereco', 'observacao', 'forma_pagamento', 'troco',
		'local_entrega', 'taxa_entrega', 'subtotal', 'total', 'atualizado_em',
	])
	return None

@dono_required
@require_POST
def pedido_excluir(request, pedido_id):
	pedido = get_object_or_404(Pedido, id=pedido_id)
	pedido.delete()
	messages.success(request, 'Pedido removido com sucesso!')
	return redirect('painel_pedidos')
@login_required(login_url='/login/')
def pedido_imprimir(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)

    itens_processados = []
    ordem_itens = Case(
        When(item_tipo='pizza', then=Value(0)),
        When(item_tipo='bebida', then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )

    for item in pedido.itens.select_related('pizza', 'bebida').order_by(ordem_itens, 'id'):
        item_data = {
            'item': item,
            'sabores_data': None,
        }

        if item.item_tipo == 'pizza':
            sabores_data = {}

            if item.sabores:
                try:
                    sabores_data = json.loads(unescape(item.sabores))
                except (TypeError, ValueError):
                    sabores_data = {}

            sabores_ids = sabores_data.get('ids', [])

            if not sabores_ids and item.pizza_id:
                sabores_ids = [item.pizza_id]

            pizzas_por_id = Pizza.objects.in_bulk(sabores_ids)

            sabores_detalhados = []
            for pizza_id in sabores_ids:
                pizza = pizzas_por_id.get(pizza_id)
                if pizza:
                    sabores_detalhados.append({
                        'nome': pizza.nome,
                        'ingredientes': pizza.ingredientes,
                    })

            sabores_data['num_sabores'] = len(sabores_detalhados)
            sabores_data['sabores_detalhados'] = sabores_detalhados
            item_data['sabores_data'] = sabores_data

        itens_processados.append(item_data)

    pizzas_processadas = [
        item for item in itens_processados
        if item['item'].item_tipo == 'pizza'
    ]
    bebidas_processadas = [
        item for item in itens_processados
        if item['item'].item_tipo == 'bebida'
    ]

    return render(request, 'pizzaria/pedido_imprimir.html', {
        'pedido': pedido,
        'itens_processados': itens_processados,
        'pizzas_processadas': pizzas_processadas,
        'bebidas_processadas': bebidas_processadas,
    })

def login_view(request):
	if request.method == 'POST':
		username = request.POST.get('username')
		password = request.POST.get('password')
		user = authenticate(request, username=username, password=password)
		if user is not None:
			login(request, user)
			if garcom_user(user):
				return redirect('painel_pedidos')
			return redirect('painel')
		else:
			return render(request, 'pizzaria/login.html', {'error': 'Usuário ou senha inválidos.'})
	return render(request, 'pizzaria/login.html')

def lista_motoqueiros_view(request):
    motoqueiros = Motoqueiro.objects.all().select_related('usuario')
    context = {
        'motoqueiros': motoqueiros,
        'active_page': 'motoqueiros',
    }
    return render(request, 'pizzaria/motoqueiro_formulario.html', context) 


@login_required(login_url='/login/')
@dono_required
def cadastrar_motoqueiro_view(request):
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        senha = request.POST.get('senha', '').strip()
        if not nome or not senha:
            messages.error(request, 'Preencha todos os campos obrigatórios.')
            return redirect('cadastrar_motoqueiro')
        username = re.sub(r'\s+', '_', nome.lower())
        username = re.sub(r'[^\w]', '', username)
        if not username:
            messages.error(request, 'Nome inválido para gerar um usuário.')
            return redirect('cadastrar_motoqueiro')
        if User.objects.filter(username=username).exists():
            username = f"{username}_{User.objects.count() + 1}"
        try:
            user = User.objects.create_user(username=username, password=senha)
            nome_partes = nome.split(' ', 1)
            user.first_name = nome_partes[0]
            if len(nome_partes) > 1:
                user.last_name = nome_partes[1]
            user.save()
            grupo_motoqueiros, _ = Group.objects.get_or_create(name='Motoqueiros')
            user.groups.add(grupo_motoqueiros)            
            messages.success(request, f'Motoqueiro {nome} cadastrado com sucesso!')
        except Exception as e:
            messages.error(request, f'Erro ao cadastrar motoqueiro: {str(e)}')
        return redirect('cadastrar_motoqueiro')
    motoqueiros_ativos = User.objects.filter(groups__name='Motoqueiros', is_active=True).order_by('first_name')
    motoqueiros_inativos = User.objects.filter(groups__name='Motoqueiros', is_active=False).order_by('first_name')
    
    context = {
        'motoqueiros': motoqueiros_ativos,
        'motoqueiros_inativos': motoqueiros_inativos
    }
    return render(request, 'pizzaria/motoqueiro_formulario.html', context)

@login_required(login_url='/login/')
@require_POST
@csrf_exempt
def vincular_motoqueiro_ao_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    motoqueiro_id = request.POST.get('motoqueiro_id')

    if not motoqueiro_id:
        messages.error(request, 'Selecione um entregador válido.')
        return redirect('painel_pedidos' if garcom_user(request.user) else 'painel')
        
    motoqueiro = get_object_or_404(User, id=motoqueiro_id, groups__name='Motoqueiros')
    
    pedido.motoqueiro_responsavel = motoqueiro 

    pedido.status = "Pronto" 
    
    pedido.save()

    messages.success(request, f'Pedido #{pedido.id} despachado com sucesso por {motoqueiro.first_name}!')
    if garcom_user(request.user):
        return redirect('painel_pedidos')
    return redirect('painel')

@login_required(login_url='/login/')
@require_POST
@csrf_exempt
def desativar_motoqueiro_view(request, user_id):

    motoqueiro = get_object_or_404(User, id=user_id, groups__name='Motoqueiros')
    motoqueiro.is_active = False
    motoqueiro.save()
    messages.success(request, f'Motoqueiro desativado com sucesso!')
    return redirect('cadastrar_motoqueiro')


@login_required(login_url='/login/')
@dono_required
@require_POST
def excluir_motoqueiro_permanente_view(request, user_id):
    motoqueiro = get_object_or_404(User, id=user_id, groups__name='Motoqueiros')
    nome_salvo = motoqueiro.get_full_name() or motoqueiro.username
    motoqueiro.delete() 
    messages.success(request, f'Motoqueiro {nome_salvo} foi excluído permanentemente.')
    return redirect('cadastrar_motoqueiro')

@login_required(login_url='/login/')
@dono_required
@require_POST
@csrf_exempt
def reativar_motoqueiro_view(request, user_id):

    motoqueiro = get_object_or_404(User, id=user_id, groups__name='Motoqueiros')
    motoqueiro.is_active = True
    motoqueiro.save()
    messages.success(request, f'Motoqueiro reativado com sucesso!')
    return redirect('cadastrar_motoqueiro')


def debug_recriar_pizzas(request):
	from django.http import HttpResponse
	count = Pizza.objects.count()
	Pizza.objects.all().delete()
	
	pizzas = [
		{'nome': 'Americana', 'ingredientes': 'Mussarela, presunto, ovo, bacon, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Bacon', 'ingredientes': 'Bacon, cebola, mussarela e azeitona', 'especial': False, 'disponivel': True},
		{'nome': 'Baiana', 'ingredientes': 'Calabresa moída, pimenta, cebola, mussarela e azeitona', 'especial': False, 'disponivel': True},
		{'nome': 'Caipira', 'ingredientes': 'Frango desfiado, milho, catupiry e azeitona', 'especial': False, 'disponivel': True},
		{'nome': 'Calabresa 1', 'ingredientes': 'Calabresa fatiada, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Calabresa 2', 'ingredientes': 'Calabresa fatiada, bacon, mussarela, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Calabresa 3', 'ingredientes': 'Mussarela por baixo, calabresa, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Calabresa 4', 'ingredientes': 'Calabresa, cheddar, mussarela, cebola, bacon e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Calacatu', 'ingredientes': 'Calabresa fatiada, catupiry, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Delícia', 'ingredientes': 'Lombinho, palmito, catupiry e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Frango Bacon 1', 'ingredientes': 'Frango, mussarela, bacon e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Frango Bacon 2', 'ingredientes': 'Frango, milho, ovo, mussarela, bacon e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Frango catupiry', 'ingredientes': 'Frango desfiado, catupiry e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Marguerita', 'ingredientes': 'Mussarela, parmesão, manjericão, tomate e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Milho', 'ingredientes': 'Mussarela e milho', 'especial': False, 'disponivel': True},
		{'nome': 'Mussarela', 'ingredientes': 'Mussarela, tomate e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Namorado', 'ingredientes': 'Palmito, catupiry, mussarela e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Napolitana', 'ingredientes': 'Mussarela, molho de tomate, parmesão e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Nordestina', 'ingredientes': 'Carne seca temperada, mussarela, cebola e azeitonas', 'especial': True, 'disponivel': True},
		{'nome': 'Portuguesa', 'ingredientes': 'Presunto, mussarela, palmito, cebola, ovo, ervilha e milho', 'especial': False, 'disponivel': True},
		{'nome': 'Toscana', 'ingredientes': 'Presunto, calabresa, ovo, mussarela, bacon e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'À moda do chefe', 'ingredientes': 'Lombo canadense, ovos, ervilha, palmito, mussarela, cebola e azeitonas', 'especial': False, 'disponivel': True},
		{'nome': 'Atum 1', 'ingredientes': 'Atum, cebola, tomate e azeitonas', 'especial': True, 'disponivel': True},
		{'nome': 'Atum 2', 'ingredientes': 'Atum, mussarela, cebola e azeitonas', 'especial': True, 'disponivel': True},
		{'nome': 'Quatro Queijos', 'ingredientes': 'Mussarela, gorgonzola, catupiry e provolone', 'especial': True, 'disponivel': True},
		{'nome': 'Chocolate 1', 'ingredientes': 'Creme de leite, chocolate, confetes e granulado', 'especial': False, 'disponivel': True},
		{'nome': 'Chocolate 2', 'ingredientes': 'Mussarela com chocolate', 'especial': False, 'disponivel': True},
	]
	
	for pizza_data in pizzas:
		Pizza.objects.create(**pizza_data)
	
	nordestina = Pizza.objects.get(nome='Nordestina')
	
	return HttpResponse(f"""
		<h1>✅ Pizzas Recriadas!</h1>
		<p>❌ {count} pizzas antigas apagadas</p>
		<p>✅ {len(pizzas)} pizzas novas criadas</p>
		<h2>🔥 Pizza Nordestina:</h2>
		<ul>
			<li>ID: {nordestina.id}</li>
			<li>Nome: {nordestina.nome}</li>
			<li>Especial: {'⭐ SIM' if nordestina.especial else '❌ NÃO'}</li>
		</ul>
		<a href="/escolher-sabores/">Ir para o site</a>
	""")

def login_view(request):
    if request.method == 'POST':
        usuario_raw = request.POST.get('username')
        senha_raw = request.POST.get('password')
        user = authenticate(request, username=usuario_raw, password=senha_raw)
        if user is not None:
            login(request, user)
            messages.success(request, f"Bem-vindo de volta, {user.username}!")
            # Redireciona o garçom direto para os pedidos ativos, outros vão para o painel geral
            if garcom_user(user):
                return redirect('painel_pedidos')
            return redirect('painel')
        else:
            messages.error(request, "Usuário ou senha inválidos.")
    return render(request, 'pizzaria/login.html')


def logout_view(request):
    logout(request)
    messages.success(request, "Você saiu do painel administrativo.")
    return redirect('login')