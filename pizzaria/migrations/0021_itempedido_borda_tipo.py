from django.db import migrations, models


def preencher_borda_tipo(apps, schema_editor):
    ItemPedido = apps.get_model('pizzaria', 'ItemPedido')
    ItemPedido.objects.filter(borda_chocolate=True).update(borda_tipo='chocolate')
    ItemPedido.objects.filter(catupiry_borda=True, borda_chocolate=False).update(borda_tipo='catupiry_original')


class Migration(migrations.Migration):
    dependencies = [('pizzaria', '0020_adicionar_novas_taxas_entrega')]
    operations = [
        migrations.AddField(
            model_name='itempedido',
            name='borda_tipo',
            field=models.CharField(choices=[('catupiry', 'Catupiry'), ('cheddar', 'Cheddar'), ('sem_borda', 'Sem borda'), ('catupiry_original', 'Catupiry Original'), ('chocolate', 'Chocolate')], default='catupiry', max_length=20),
        ),
        migrations.RunPython(preencher_borda_tipo, migrations.RunPython.noop),
    ]