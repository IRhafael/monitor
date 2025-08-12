from django import template

register = template.Library()

@register.filter
def get_field_value(obj, field_name):
    """Retorna o valor de um campo do modelo pelo nome."""
    return getattr(obj, field_name, None)

@register.simple_tag
def model_fields(obj):
    """Retorna uma lista dos nomes dos campos do modelo."""
    return [field.name for field in obj._meta.fields]
