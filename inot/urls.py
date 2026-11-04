from django.urls import path

from . import views as v

urlpatterns = [
    path('disponibil/', v.DisponibilitateView.as_view()),
    path('programeaza/', v.ProgrameazaView.as_view()),

    path('auth/register/', v.InregistrareView.as_view()),
    path('auth/login/', v.AutentificareView.as_view()),
    path('auth/logout/', v.IesireView.as_view()),
    path('auth/reset/', v.ResetareCerereView.as_view()),
    path('auth/reset/confirma/', v.ResetareConfirmaView.as_view()),
    path('cont/', v.ContView.as_view()),

    path('programarile-mele/', v.ProgramarileMeleView.as_view()),
    path('programari/<int:pk>/anuleaza/', v.AnuleazaView.as_view()),
    path('programari/<int:pk>/reprogrameaza/', v.ReprogrameazaView.as_view()),

    path('instructor/zi/', v.InstructorZiView.as_view()),
    path('instructor/programari/<int:pk>/', v.InstructorProgramareView.as_view()),
    path('instructor/export/', v.InstructorExportView.as_view()),

    path('superadmin/instructori/', v.InstructoriView.as_view()),
    path('superadmin/instructori/<int:pk>/', v.InstructorContView.as_view()),
]
