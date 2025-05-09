from django.contrib import admin
from django.urls import path, include  # Adicione o 'include'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('monitor.urls')),  # Esta linha é crucial
]