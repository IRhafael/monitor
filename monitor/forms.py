
# forms.py simplificado
from django import forms
from django.core.exceptions import ValidationError
from .models import Documento

class DocumentoUploadForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['titulo', 'data_publicacao', 'arquivo_pdf']

    def clean_arquivo_pdf(self):
        pdf_file = self.cleaned_data.get('arquivo_pdf')
        if pdf_file:
            if not pdf_file.name.lower().endswith('.pdf'):
                raise ValidationError('O arquivo deve ser um PDF')
            if pdf_file.size > 10 * 1024 * 1024:  # 10MB
                raise ValidationError('O arquivo não pode exceder 10MB')
        return pdf_file