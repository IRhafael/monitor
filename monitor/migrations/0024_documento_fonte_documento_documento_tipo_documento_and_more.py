# Generated by Django 5.2.1 on 2025-05-28 18:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0023_alter_normavigente_data_verificacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='documento',
            name='fonte_documento',
            field=models.CharField(blank=True, max_length=250, null=True, verbose_name='Fonte do Documento'),
        ),
        migrations.AddField(
            model_name='documento',
            name='tipo_documento',
            field=models.CharField(blank=True, choices=[('DIARIO_OFICIAL', 'Diário Oficial'), ('PORTARIA_DOC', 'Portaria do Documento'), ('EDITAL', 'Edital'), ('COMUNICADO', 'Comunicado'), ('ATO_NORMATIVO_DOC', 'Ato Normativo do Documento'), ('LEI_DOC', 'Lei do Documento'), ('DECRETO_DOC', 'Decreto do Documento'), ('RESOLUCAO_DOC', 'Resolução do Documento'), ('INSTRUCAO_NORMATIVA_DOC', 'Instrução Normativa do Documento'), ('OUTRO', 'Outro')], max_length=50, null=True, verbose_name='Tipo do Documento'),
        ),
        migrations.AddField(
            model_name='normavigente',
            name='data_vigencia',
            field=models.DateField(blank=True, null=True, verbose_name='Data de Início da Vigência'),
        ),
        migrations.AddField(
            model_name='normavigente',
            name='ementa',
            field=models.TextField(blank=True, null=True, verbose_name='Ementa da Norma'),
        ),
        migrations.AddIndex(
            model_name='documento',
            index=models.Index(fields=['tipo_documento'], name='monitor_doc_tipo_do_35d423_idx'),
        ),
        migrations.AddIndex(
            model_name='normavigente',
            index=models.Index(fields=['data_vigencia'], name='monitor_nor_data_vi_5e0d9b_idx'),
        ),
    ]
