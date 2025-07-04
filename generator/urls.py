from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('edit/', views.edit_readme, name='edit_readme'),
    path('edit/save/', views.save_readme, name='save_readme'),
]