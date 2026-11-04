from datetime import date, timedelta

from django.contrib import admin

from .export import export_saptamana_response
from .models import Profil, Programare, Sablon, Setari, ZiInchisa


@admin.register(Programare)
class ProgramareAdmin(admin.ModelAdmin):
    list_display = ('data', 'ora', 'grupa', 'nume_copil', 'varsta', 'nume_parinte', 'telefon', 'status')
    list_filter = ('data', 'grupa', 'status', 'sablon')
    search_fields = ('nume_copil', 'nume_parinte', 'telefon', 'email')
    date_hierarchy = 'data'
    list_editable = ('status',)
    list_select_related = ('sablon',)
    actions = ['export_excel', 'marcheaza_anulat']

    @admin.display(description='Ora', ordering='sablon__ora_start')
    def ora(self, obj):
        return obj.sablon.ora_start.strftime('%H:%M')

    @admin.action(description='Exportă Excel (săptămâna primei programări selectate)')
    def export_excel(self, request, queryset):
        prima = queryset.order_by('data').first()
        zi = prima.data if prima else date.today()
        return export_saptamana_response(zi - timedelta(days=zi.weekday()))

    @admin.action(description='Anulează programările selectate')
    def marcheaza_anulat(self, request, queryset):
        queryset.update(status='anulat')


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ('nume', 'telefon', 'user')
    search_fields = ('nume', 'telefon', 'user__email')


@admin.register(Sablon)
class SablonAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'activ')
    list_editable = ('activ',)


@admin.register(ZiInchisa)
class ZiInchisaAdmin(admin.ModelAdmin):
    list_display = ('data', 'motiv')


@admin.register(Setari)
class SetariAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not Setari.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
