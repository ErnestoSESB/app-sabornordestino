from django.db import models
from .utils import SanitizedModelMixin

class TaxaEntrega(SanitizedModelMixin, models.Model):
	nome = models.CharField(max_length=100, unique=True, help_text='Nome da localidade')
	taxa = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='Valor da taxa de entrega')
	ativo = models.BooleanField(default=True, help_text='Se a entrega está disponível para este local')
	
	def __str__(self):
		return f"{self.nome} - R$ {self.taxa:.2f}"
	
	class Meta:
		verbose_name = 'Taxa de Entrega'
		verbose_name_plural = 'Taxas de Entrega'
		ordering = ['nome']


class Pizza(SanitizedModelMixin, models.Model):
	CATEGORIA_SALGADA = 'salgada'
	CATEGORIA_DOCE = 'doce'
	CATEGORIA_CHOICES = [
		(CATEGORIA_SALGADA, 'Pizza salgada'),
		(CATEGORIA_DOCE, 'Pizza doce'),
	]

	nome = models.CharField(max_length=100)
	ingredientes = models.CharField(max_length=255)
	imagem = models.ImageField(upload_to='pizzas/', blank=True, null=True)
	categoria = models.CharField(max_length=10, choices=CATEGORIA_CHOICES, default=CATEGORIA_SALGADA)
	disponivel = models.BooleanField(default=True)
	criado_em = models.DateTimeField(auto_now_add=True)
	especial = models.BooleanField(default=False, help_text='Atum, Carne de Sol ou 4 Queijos')

	def __str__(self):
		return self.nome

	def get_preco(self, tamanho):
		"""Retorna o preço base conforme o tamanho"""
		precos_base = {'P': 25.00, 'M': 32.00, 'G': 39.00}
		return precos_base.get(tamanho, 0)


class Bebida(SanitizedModelMixin, models.Model):
	nome = models.CharField(max_length=100)
	descricao = models.CharField(max_length=200, blank=True)
	imagem = models.ImageField(upload_to='bebidas/', blank=True, null=True)
	preco = models.DecimalField(max_digits=6, decimal_places=2, default=0)
	disponivel = models.BooleanField(default=True)
	criado_em = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.nome

	class Meta:
		verbose_name = 'Bebida'
		verbose_name_plural = 'Bebidas'
		ordering = ['nome']


class Pedido(SanitizedModelMixin, models.Model):
	STATUS_CHOICES = [
		("Novo", "Novo"),
		("Em andamento", "Em andamento"),
		("Em preparo", "Em preparo"),
		("Pronto", "Pronto"),
		("Entregue", "Entregue"),
		("Pago", "Pago"),
	]
	cliente = models.CharField(max_length=100)
	cliente_token = models.CharField(max_length=64, blank=True, default='', db_index=True)
	telefone = models.CharField(max_length=20, blank=True, default="")
	endereco = models.TextField(blank=True, null=True)
	observacao = models.TextField(blank=True, null=True)
	forma_pagamento = models.CharField(max_length=30, default='', blank=True)
	troco = models.CharField(max_length=30, default='', blank=True)
	local_entrega = models.ForeignKey(TaxaEntrega, on_delete=models.SET_NULL, null=True, blank=True, help_text='Local de entrega (se aplicável)')
	taxa_entrega = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='Valor da taxa de entrega')
	subtotal = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text='Total sem taxa de entrega')
	total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Novo")
	criado_em = models.DateTimeField(auto_now_add=True)
	atualizado_em = models.DateTimeField(auto_now=True)
	reaberto_em = models.DateTimeField(null=True, blank=True)
	fechado_em = models.DateTimeField(null=True, blank=True)

	def __str__(self):
		return f"Pedido #{self.id} - {self.cliente}"

class ItemPedido(SanitizedModelMixin, models.Model):
	TIPO_CHOICES = [
		('pizza', 'Pizza'),
		('bebida', 'Bebida'),
	]
	pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
	item_tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='pizza')
	pizza = models.ForeignKey(Pizza, on_delete=models.CASCADE, null=True, blank=True, related_name='itens_pedido')
	bebida = models.ForeignKey(Bebida, on_delete=models.CASCADE, null=True, blank=True, related_name='itens_pedido')
	quantidade = models.PositiveIntegerField(default=1)
	preco_unitario = models.DecimalField(max_digits=6, decimal_places=2)
	sabores = models.TextField(blank=True, null=True, help_text='JSON com sabores múltiplos')
	tamanho = models.CharField(max_length=1, choices=[('P', 'Pequena'), ('M', 'Média'), ('G', 'Grande')], default='G')
	borda_chocolate = models.BooleanField(default=False)
	catupiry_cima = models.CharField(max_length=10, choices=[('nao', 'Não'), ('inteira', 'Inteira'), ('metade', 'Metade')], default='nao')
	catupiry_borda = models.BooleanField(default=False)
	
	def __str__(self):
		if self.item_tipo == 'bebida' and self.bebida:
			return f"{self.quantidade}x {self.bebida.nome}"
		if self.pizza:
			return f"{self.quantidade}x {self.pizza.nome}"
		return f"Item {self.id}"
	
	@property
	def subtotal(self):
		return self.quantidade * self.preco_unitario
