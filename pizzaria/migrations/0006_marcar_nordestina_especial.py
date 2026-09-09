# Generated migration
from django.db import migrations

def marcar_nordestina_especial(apps, schema_editor):
    """Marca a pizza Nordestina como especial"""
    Pizza = apps.get_model('pizzaria', 'Pizza')
    try:
        nordestina = Pizza.objects.get(nome='Nordestina')
        if not nordestina.especial:
            nordestina.especial = True
            nordestina.save()
            print('Pizza Nordestina marcada como especial!')
        else:
            print('Pizza Nordestina ja esta especial')
    except Pizza.DoesNotExist:
        print('Pizza Nordestina nao encontrada')

def reverter(apps, schema_editor):
    """Reverte a alteração"""
    Pizza = apps.get_model('pizzaria', 'Pizza')
    try:
        nordestina = Pizza.objects.get(nome='Nordestina')
        nordestina.especial = False
        nordestina.save()
    except Pizza.DoesNotExist:
        pass

class Migration(migrations.Migration):

    dependencies = [
        ('pizzaria', '0005_taxaentrega_pedido_subtotal_pedido_taxa_entrega_and_more'),
    ]

    operations = [
        migrations.RunPython(marcar_nordestina_especial, reverter),
    ]
