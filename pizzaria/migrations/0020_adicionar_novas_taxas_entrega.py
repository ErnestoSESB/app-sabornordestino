from django.db import migrations


def adicionar_taxas(apps, schema_editor):
    TaxaEntrega = apps.get_model('pizzaria', 'TaxaEntrega')
    for nome in ('Fogueteiro', 'Baixio de Onça'):
        TaxaEntrega.objects.get_or_create(
            nome=nome,
            defaults={'taxa': 6.00, 'ativo': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('pizzaria', '0019_normalizar_nomes_taxas_entrega'),
    ]

    operations = [
        migrations.RunPython(adicionar_taxas, migrations.RunPython.noop),
    ]
