"""
Django management command para popular dados iniciais
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from pizzaria.models import Bebida, Pizza, TaxaEntrega

User = get_user_model()

class Command(BaseCommand):
    help = 'Popula dados iniciais no banco de dados'

    def handle(self, *args, **options):
        self.stdout.write('🚀 Iniciando configuração...\n')
        
        # Criar superusuário
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin',
                password='pizzaria2025',
                email='admin@sabornordestino.com'
            )
            self.stdout.write(self.style.SUCCESS('✅ Superusuário criado: admin / pizzaria2025'))
        else:
            self.stdout.write('ℹ️ Superusuário já existe')
        
        # Criar taxas de entrega
        taxas = [
            {'nome': 'Lucrécia', 'taxa': 0.00},
            {'nome': 'Lucrécia (Sitio)', 'taxa': 0.00},
            {'nome': 'Três Altos', 'taxa': 6.00},
            {'nome': 'Almino Afonso', 'taxa': 6.00},
            {'nome': 'Frutuoso Gomes', 'taxa': 6.00},
            {'nome': 'Fogueteiro', 'taxa': 6.00},
            {'nome': 'Baixio de Onça', 'taxa': 6.00},
        ]
        
        for taxa_data in taxas:
            taxa, created = TaxaEntrega.objects.get_or_create(
                nome=taxa_data['nome'],
                defaults={'taxa': taxa_data['taxa']}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Taxa criada: {taxa.nome} - R$ {taxa.taxa:.2f}'))
        
        # Criar pizzas básicas
        if Pizza.objects.count() == 0:
            pizzas = [
                # PIZZAS TRADICIONAIS
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
                
                # PIZZAS ESPECIAIS (⭐ +R$ 2 ou 4)
                {'nome': 'Atum 1', 'ingredientes': 'Atum, cebola, tomate e azeitonas', 'especial': True, 'disponivel': True},
                {'nome': 'Atum 2', 'ingredientes': 'Atum, mussarela, cebola e azeitonas', 'especial': True, 'disponivel': True},
                {'nome': 'Quatro Queijos', 'ingredientes': 'Mussarela, gorgonzola, catupiry e provolone', 'especial': True, 'disponivel': True},
                
                # PIZZAS DOCES (🍫)
                {'nome': 'Chocolate 1', 'ingredientes': 'Creme de leite, chocolate, confetes e granulado', 'especial': False, 'disponivel': True},
                {'nome': 'Chocolate 2', 'ingredientes': 'Mussarela com chocolate', 'especial': False, 'disponivel': True},
            ]
            
            for pizza_data in pizzas:
                Pizza.objects.create(**pizza_data)
                emoji = '⭐' if pizza_data['especial'] else '🍕'
                self.stdout.write(self.style.SUCCESS(f'✅ Pizza criada: {emoji} {pizza_data["nome"]}'))
        else:
            self.stdout.write(f'ℹ️ Já existem {Pizza.objects.count()} pizzas cadastradas')

        bebidas = [
            {'nome': 'Coca-Cola Lata', 'descricao': 'Refrigerante 350 ml', 'preco': 6.00, 'disponivel': True},
            {'nome': 'Guarana Antarctica Lata', 'descricao': 'Refrigerante 350 ml', 'preco': 6.00, 'disponivel': True},
            {'nome': 'Fanta Laranja Lata', 'descricao': 'Refrigerante 350 ml', 'preco': 6.00, 'disponivel': True},
            {'nome': 'Agua Mineral', 'descricao': 'Agua mineral 500 ml', 'preco': 3.00, 'disponivel': True},
        ]

        for bebida_data in bebidas:
            bebida, created = Bebida.objects.get_or_create(
                nome=bebida_data['nome'],
                defaults=bebida_data,
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Bebida criada: {bebida.nome}'))
        
        self.stdout.write(self.style.SUCCESS('\n✨ Configuração concluída!'))
