"""Reference URLconf with the names required by the Projects frontend."""

from django.urls import path

from apps.projects import views


app_name = 'personal'

urlpatterns = [
    path('projects/', views.project_list, name='projects'),
    path('projects/<slug:category>/', views.project_category, name='projects-category'),
    path('projects/project/<slug:slug>/', views.project_detail, name='project-detail'),
]
