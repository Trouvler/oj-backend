# Generated by Django 3.2.9 on 2022-10-18 12:40

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SysOptions',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.TextField(db_index=True, unique=True)),
                ('value', models.JSONField()),
            ],
        ),
    ]
