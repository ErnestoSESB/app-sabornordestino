from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pizzaria', '0007_pizza_imagem'),
    ]

    operations = [
        migrations.AddField(
            model_name='pizza',
            name='categoria',
            field=models.CharField(
                choices=[('salgada', 'Pizza salgada'), ('doce', 'Pizza doce')],
                default='salgada',
                max_length=10,
            ),
        ),
    ]
