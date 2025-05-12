# monitor/admin.py
from django.contrib import admin
from .models import Norma

@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'numero', 'data']
    search_fields = ['numero', 'tipo']