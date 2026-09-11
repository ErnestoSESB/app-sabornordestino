from django.db import migrations


def normalizar_nomes_taxas(apps, schema_editor):
    TaxaEntrega = apps.get_model('pizzaria', 'TaxaEntrega')
    Pedido = apps.get_model('pizzaria', 'Pedido')

    for taxa in list(TaxaEntrega.objects.all().order_by('id')):
        try:
            nome_correto = taxa.nome.encode('latin1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

        if nome_correto == taxa.nome:
            continue

        existente = TaxaEntrega.objects.filter(nome=nome_correto).exclude(pk=taxa.pk).first()
        if existente:
            Pedido.objects.filter(local_entrega_id=taxa.pk).update(local_entrega_id=existente.pk)
            taxa.delete()
        else:
            taxa.nome = nome_correto
            taxa.save(update_fields=['nome'])


class Migration(migrations.Migration):

    dependencies = [
        ('pizzaria', '0018_pedido_motoqueiro'),
    ]

    operations = [
        migrations.RunPython(normalizar_nomes_taxas, migrations.RunPython.noop),
    ]
