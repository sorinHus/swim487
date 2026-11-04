from django.urls import path

from .views import DisponibilitateView, ProgrameazaView

urlpatterns = [
    path('disponibil/', DisponibilitateView.as_view()),
    path('programeaza/', ProgrameazaView.as_view()),
]
