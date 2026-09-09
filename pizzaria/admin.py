from django.contrib import admin
from .models import Pizza, Pedido, ItemPedido, TaxaEntrega, Bebida

@admin.register(TaxaEntrega)
class TaxaEntregaAdmin(admin.ModelAdmin):
	list_display = ('nome', 'taxa', 'ativo')
	list_filter = ('ativo',)
	search_fields = ('nome',)
	list_editable = ('taxa', 'ativo')

@admin.register(Bebida)
class BebidaAdmin(admin.ModelAdmin):
	list_display = ('nome', 'preco', 'disponivel', 'criado_em')
	list_filter = ('disponivel',)
	search_fields = ('nome', 'descricao')
	list_editable = ('preco', 'disponivel')

@admin.register(Pizza)
class PizzaAdmin(admin.ModelAdmin):
	list_display = ('nome', 'categoria', 'especial', 'disponivel', 'criado_em')
	list_filter = ('categoria', 'especial', 'disponivel')
	search_fields = ('nome', 'ingredientes')
	list_editable = ('disponivel',)

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
	list_display = ('id', 'cliente', 'local_entrega', 'taxa_entrega', 'subtotal', 'total', 'status', 'criado_em')
	list_filter = ('status', 'criado_em', 'local_entrega')
	search_fields = ('cliente', 'endereco')
	readonly_fields = ('criado_em', 'atualizado_em')
	
@admin.register(ItemPedido)
class ItemPedidoAdmin(admin.ModelAdmin):
	list_display = ('pedido', 'item_tipo', 'pizza', 'bebida', 'tamanho', 'quantidade', 'preco_unitario', 'subtotal')
	list_filter = ('item_tipo', 'tamanho')
	search_fields = ('pedido__cliente', 'pizza__nome', 'bebida__nome')

