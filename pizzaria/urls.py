from django.urls import path
from django.conf import settings
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Painel do usuario
    path('', views.index, name='index'),
    path('cardapio/', views.cardapio, name='cardapio'),
    path('contato/', views.contato, name='contato'),
    path('escolher-sabores/', views.escolher_sabores, name='escolher_sabores'),
    path('carrinho/', views.carrinho_detalhes, name='carrinho_detalhes'),
    path('carrinho/adicionar/<int:pizza_id>/', views.carrinho_adicionar, name='carrinho_adicionar'),
    path('carrinho/adicionar-pizza/', views.carrinho_adicionar_pizza, name='carrinho_adicionar_pizza'),
    path('carrinho/remover/<str:item_id>/', views.carrinho_remover, name='carrinho_remover'),
    path('carrinho/finalizar/', views.carrinho_finalizar, name='carrinho_finalizar'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Painel do dono
    path('painel/pedido/<int:pedido_id>/vincular/', views.vincular_motoqueiro_ao_pedido, name='vincular_motoqueiro'),
    path('painel/motoqueiros/cadastrar/', views.cadastrar_motoqueiro_view, name='cadastrar_motoqueiro'),
    path('painel/motoqueiros/', views.lista_motoqueiros_view, name='lista_motoqueiros'),
    path('painel/motoqueiros/desativar/<int:user_id>/', views.desativar_motoqueiro_view, name='desativar_motoqueiro'),
     path('painel/motoqueiros/excluir/<int:user_id>/', views.excluir_motoqueiro_permanente_view, name='excluir_motoqueiro_permanente'),
     path('painel/motoqueiros/reativar/<int:user_id>/', views.reativar_motoqueiro_view, name='reativar_motoqueiro'),
    path('controle/', views.painel, name='painel'),
    path('painel/', RedirectView.as_view(pattern_name='painel', permanent=False)),
    path('painel/pizzas/', views.painel_pizzas, name='painel_pizzas'),
    path('painel/pizzas/adicionar/', views.pizza_adicionar, name='pizza_adicionar'),
    path('painel/pizzas/editar/<int:pizza_id>/', views.pizza_editar, name='pizza_editar'),
    path('painel/pizzas/excluir/<int:pizza_id>/', views.pizza_excluir, name='pizza_excluir'),
    path('painel/bebidas/', views.painel_bebidas, name='painel_bebidas'),
    path('painel/bebidas/adicionar/', views.bebida_adicionar, name='bebida_adicionar'),
    path('painel/bebidas/editar/<int:bebida_id>/', views.bebida_editar, name='bebida_editar'),
    path('painel/bebidas/excluir/<int:bebida_id>/', views.bebida_excluir, name='bebida_excluir'),
    path('painel/pedidos/', views.painel_pedidos, name='painel_pedidos'),
    path('painel/historico-pedidos/', views.historico_pedidos, name='historico_pedidos'),
    path('painel/garcons/', views.painel_garcons, name='painel_garcons'),
    path('painel/garcons/adicionar/', views.garcom_adicionar, name='garcom_adicionar'),
    path('painel/garcons/excluir/<int:user_id>/', views.garcom_excluir, name='garcom_excluir'),
    path('painel/garcons/ativar/<int:user_id>/', views.garcom_ativar, name='garcom_ativar'),
    path('painel/garcons/deletar-permanente/<int:user_id>/', views.garcom_deletar_permanente, name='garcom_deletar_permanente'),
    path('painel/pedidos/reabrir/<int:pedido_id>/', views.pedido_reabrir, name='pedido_reabrir'),
    path('painel/pedidos/adicionar/', views.pedido_adicionar, name='pedido_adicionar'),
    path('painel/pedidos/status/<int:pedido_id>/', views.pedido_alterar_status, name='pedido_alterar_status'),
    path('painel/pedidos/excluir/<int:pedido_id>/', views.pedido_excluir, name='pedido_excluir'),
    path('painel/pedidos/imprimir/<int:pedido_id>/', views.pedido_imprimir, name='pedido_imprimir'),
    
]

if settings.DEBUG:
    urlpatterns += [
        path('debug/recriar-pizzas/', views.debug_recriar_pizzas, name='debug_recriar_pizzas'),
    ]
