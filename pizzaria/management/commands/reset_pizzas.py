"""
Django management command para resetar as pizzas
"""
from django.core.management.base import BaseCommand
from pizzaria.models import Pizza

class Command(BaseCommand):
    help = 'Remove todas as pizzas e recria com os dados corretos'

    def handle(self, *args, **options):
        self.stdout.write('🔄 Resetando pizzas...\n')
        
        # Deletar todas as pizzas existentes
        count = Pizza.objects.count()
        Pizza.objects.all().delete()
        self.stdout.write(self.style.WARNING(f'🗑️ {count} pizzas antigas removidas'))
        
        # Recriar pizzas
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
            {'nome': 'Nordestina', 'ingredientes': 'Carne seca temperada, mussarela, cebola e azeitonas', 'especial': False, 'disponivel': True},
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
            self.stdout.write(self.style.SUCCESS(f'✅ {emoji} {pizza_data["nome"]}'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✨ Total: {len(pizzas)} pizzas criadas!'))
