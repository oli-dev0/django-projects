from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='project', name='title', field=models.CharField(max_length=200, null=True)),
        migrations.AddField(model_name='project', name='slug', field=models.SlugField(db_index=False, max_length=220, null=True)),
        migrations.AddField(model_name='project', name='summary', field=models.TextField(null=True)),
        migrations.AddField(model_name='project', name='body', field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name='project', name='seo_title', field=models.CharField(blank=True, max_length=70, null=True)),
        migrations.AddField(model_name='project', name='seo_description', field=models.CharField(blank=True, max_length=160, null=True)),
        migrations.DeleteModel(name='ProjectTranslation'),
        migrations.AlterField(model_name='project', name='title', field=models.CharField(max_length=200)),
        migrations.AlterField(model_name='project', name='slug', field=models.SlugField(max_length=220, unique=True)),
        migrations.AlterField(model_name='project', name='summary', field=models.TextField()),
        migrations.AlterField(model_name='project', name='body', field=models.TextField(blank=True)),
        migrations.AlterField(model_name='project', name='seo_title', field=models.CharField(blank=True, max_length=70)),
        migrations.AlterField(model_name='project', name='seo_description', field=models.CharField(blank=True, max_length=160)),
    ]
