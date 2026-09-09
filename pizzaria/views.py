from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Case, IntegerField, Value, When
from datetime import datetime, timedelta
from html import unescape
from .models import Pizza, Pedido, ItemPedido, Bebida
from .carrinho import Carrinho
from .calculadora_preco import calcular_preco_pizza
from urllib.parse import quote
import json
import uuid
import re
from functools import wraps
from .models import Usuario, Motoqueiro 
from django.views.decorators.csrf import csrf_exempt



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
		'bebidas': bebidas
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
		
		# Coletar sabores
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
			catupiry_borda=catupiry_borda
		)
		
		# Criar descrição
		tamanhos = {'P': 'Pequena', 'M': 'Média', 'G': 'Grande'}
		descricao = f"{tamanhos[tamanho]} - {' / '.join(sabores_nomes)}"
		
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
		'Almino Afonso',
		'Frutuoso Gomes'
	]
	
	# Buscar taxas ativas e ordenar manualmente
	taxas_dict = {taxa.nome: taxa for taxa in TaxaEntrega.objects.filter(ativo=True)}
	taxas_entrega = [taxas_dict[nome] for nome in ordem_locais if nome in taxas_dict]
	
	# Processar sabores para o template
	itens_processados = []
	for item in carrinho:
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
			'tem_adicionais': (
				item.get('borda_chocolate', False)
				or item.get('catupiry_cima', 'nao') != 'nao'
				or item.get('catupiry_borda', False)
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
		status='Em andamento'
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
			sabores=item.get('sabores'),
			tamanho=item.get('tamanho', 'G'),
			borda_chocolate=item.get('borda_chocolate', False),
			catupiry_cima=item.get('catupiry_cima', 'nao'),
			catupiry_borda=item.get('catupiry_borda', False)
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
	
	hoje = timezone.now().date()
	
	# Contadores básicos
	pizzas_total = Pizza.objects.count()
	pedidos_hoje = Pedido.objects.filter(criado_em__date=hoje).count()
	pedidos_novos = Pedido.objects.filter(status='Novo').count()
	
	# Faturamento
	faturamento_hoje = Pedido.objects.filter(criado_em__date=hoje).aggregate(total=Sum('total'))['total'] or 0
	
	sete_dias_atras = hoje - timedelta(days=7)
	faturamento_semana = Pedido.objects.filter(criado_em__date__gte=sete_dias_atras).aggregate(total=Sum('total'))['total'] or 0
	
	trinta_dias_atras = hoje - timedelta(days=30)
	faturamento_mes = Pedido.objects.filter(criado_em__date__gte=trinta_dias_atras).aggregate(total=Sum('total'))['total'] or 0
	faturamento_bruto = Pedido.objects.aggregate(total=Sum('total'))['total'] or 0

	# Série diária usada pelo gráfico de vendas do dashboard
	primeiro_pedido = Pedido.objects.order_by('criado_em').values_list('criado_em', flat=True).first()
	data_inicial_grafico = timezone.localtime(primeiro_pedido).date() if primeiro_pedido else hoje
	grafico_vendas = []
	for dias_desde_inicio in range((hoje - data_inicial_grafico).days + 1):
		data = data_inicial_grafico + timedelta(days=dias_desde_inicio)
		total_dia = Pedido.objects.filter(criado_em__date=data).aggregate(total=Sum('total'))['total'] or 0
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
	pedidos_ontem = Pedido.objects.filter(criado_em__date=hoje - timedelta(days=1)).count()
	pedidos_semana = Pedido.objects.filter(criado_em__date__gte=sete_dias_atras).count()
	
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
@login_required(login_url='/login/')
def painel_pedidos(request):
	filtro = request.GET.get('filtro', 'hoje')
	data_especifica = request.GET.get('data', '')
	if garcom_user(request.user):
		base_pedidos = Pedido.objects.filter(usuario=request.user)
	else:
		base_pedidos = Pedido.objects.all()

	if data_especifica:
		try:
			from datetime import datetime
			data_obj = datetime.strptime(data_especifica, '%Y-%m-%d').date()
			pedidos = base_pedidos.filter(criado_em__date=data_obj)
			filtro = 'data'
		except ValueError:
			data_especifica = ''
			pedidos = base_pedidos.filter(criado_em__date=timezone.now().date())
	else:
		# Filtrar por data padrão
		hoje = timezone.now().date()
		if filtro == 'hoje':
			pedidos = base_pedidos.filter(criado_em__date=hoje)
		elif filtro == 'ontem':
			ontem = hoje - timedelta(days=1)
			pedidos = base_pedidos.filter(criado_em__date=ontem)
		elif filtro == '7dias':
			sete_dias_atras = hoje - timedelta(days=7)
			pedidos = base_pedidos.filter(criado_em__date__gte=sete_dias_atras)
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
		pedidos_processados.append(pedido)

	motoqueiros_lista = User.objects.filter(groups__name='Motoqueiros', is_active=True).order_by('first_name')
	
	return render(request, 'pizzaria/painel_pedidos.html', {
		'pedidos': pedidos_processados, 
		'active_page': 'pedidos',
		'filtro_atual': filtro,
		'data_filtro': data_especifica,
		'motoqueiros_lista': motoqueiros_lista,
	})

@login_required(login_url='/login/')
def historico_pedidos(request):
	data_filtro = request.GET.get('data', '')
	pedidos = Pedido.objects.all()
	if data_filtro:
		try:
			data_obj = datetime.strptime(data_filtro, '%Y-%m-%d').date()
			pedidos = pedidos.filter(criado_em__date=data_obj)
		except ValueError:
			data_filtro = ''
	pedidos = pedidos.prefetch_related('itens__pizza', 'itens__bebida').order_by('-criado_em')
	for pedido in pedidos:
		for item in pedido.itens.all():
			item.sabores_nomes = []
			if item.sabores:
				try:
					item.sabores_nomes = json.loads(unescape(item.sabores)).get('nomes', [])
				except (TypeError, ValueError):
					pass
	return render(request, 'pizzaria/historico_pedidos.html', {'pedidos': pedidos, 'data_filtro': data_filtro, 'active_page': 'historico'})

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

@login_required(login_url='/login/')
def pedido_adicionar(request):
	if request.method == 'POST':
		cliente = request.POST.get('cliente')
		telefone = request.POST.get('telefone')
		endereco = request.POST.get('endereco', '')
		observacao = request.POST.get('observacao', '')
		
		pedido = Pedido.objects.create(
			usuario=request.user,
			cliente=cliente,
			telefone=telefone,
			endereco=endereco,
			observacao=observacao,
			total=0
		)
		
		# Adicionar itens ao pedido
		sabores_1_ids = request.POST.getlist('sabor_1[]')
		# Compatibilidade com versoes antigas do formulario
		if not sabores_1_ids:
			sabores_1_ids = request.POST.getlist('pizza_id[]')
		numeros_sabores = request.POST.getlist('num_sabores[]')
		sabores_2_ids = request.POST.getlist('sabor_2[]')
		sabores_3_ids = request.POST.getlist('sabor_3[]')
		quantidades = request.POST.getlist('quantidade[]')
		tamanhos = request.POST.getlist('tamanho[]')
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

			try:
				quantidade = max(1, int(quantidade_raw))
			except ValueError:
				quantidade = 1

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
				borda_chocolate=False,
				catupiry_cima='nao',
				catupiry_borda=False
			)

			sabores_json = None
			if total_sabores > 1:
				tamanhos = {'P': 'Pequena', 'M': 'Media', 'G': 'Grande'}
				nomes = [sabor.nome for sabor in sabores_escolhidos]
				sabores_json = json.dumps({
					'num_sabores': total_sabores,
					'ids': [sabor.id for sabor in sabores_escolhidos],
					'nomes': nomes,
					'descricao': f"{tamanhos[tamanho]} - {' / '.join(nomes)}"
				})

			ItemPedido.objects.create(
				pedido=pedido,
				item_tipo='pizza',
				pizza=sabores_escolhidos[0],
				quantidade=quantidade,
				preco_unitario=preco_unitario,
				tamanho=tamanho,
				sabores=sabores_json
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
		
		pedido.total = total
		pedido.save()
		return redirect('painel_pedidos')
	
	pizzas = Pizza.objects.filter(disponivel=True)
	bebidas = Bebida.objects.filter(disponivel=True)
	return render(request, 'pizzaria/pedido_form.html', {
		'pizzas': pizzas,
		'bebidas': bebidas,
		'active_page': 'pedidos'
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
@login_required(login_url='/login/')
def pedido_imprimir(request, pedido_id):
	pedido = get_object_or_404(Pedido, id=pedido_id)
	
	# Processar itens com sabores
	itens_processados = []
	ordem_itens = Case(
		When(item_tipo='pizza', then=Value(0)),
		When(item_tipo='bebida', then=Value(1)),
		default=Value(2),
		output_field=IntegerField(),
	)
	for item in pedido.itens.order_by(ordem_itens, 'id'):
		item_data = {
			'item': item,
			'sabores_data': None
		}
		if item.sabores:
			try:
				item_data['sabores_data'] = json.loads(unescape(item.sabores))
			except:
				pass
		itens_processados.append(item_data)
	pizzas_processadas = [item for item in itens_processados if item['item'].item_tipo == 'pizza']
	bebidas_processadas = [item for item in itens_processados if item['item'].item_tipo == 'bebida']
	
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