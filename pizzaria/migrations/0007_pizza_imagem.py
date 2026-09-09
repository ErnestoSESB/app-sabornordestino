from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pizzaria', '0006_marcar_nordestina_especial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pizza',
            name='imagem',
            field=models.ImageField(blank=True, null=True, upload_to='pizzas/'),
        ),
    ]
