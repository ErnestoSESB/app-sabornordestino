"""
Django management command para marcar Nordestina como especial
"""
from django.core.management.base import BaseCommand
from pizzaria.models import Pizza

class Command(BaseCommand):
    help = 'Marca a pizza Nordestina como especial'

    def handle(self, *args, **options):
        try:
            nordestina = Pizza.objects.get(nome='Nordestina')
            self.stdout.write(f'\n📋 Status atual:')
            self.stdout.write(f'   Nome: {nordestina.nome}')
            self.stdout.write(f'   Especial: {nordestina.especial}')
            
            if not nordestina.especial:
                nordestina.especial = True
                nordestina.save()
                self.stdout.write(self.style.SUCCESS('\n✅ Pizza Nordestina atualizada para ESPECIAL!'))
            else:
                self.stdout.write(self.style.WARNING('\nℹ️ Pizza Nordestina já está marcada como especial'))
                
            # Listar todas as pizzas especiais
            self.stdout.write('\n⭐ Pizzas especiais cadastradas:')
            especiais = Pizza.objects.filter(especial=True).order_by('nome')
            for pizza in especiais:
                self.stdout.write(f'   - {pizza.nome}')
                
        except Pizza.DoesNotExist:
            self.stdout.write(self.style.ERROR('❌ Pizza Nordestina não encontrada no banco de dados'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro: {e}'))
