from datetime import date, timedelta

from django.contrib import admin
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .models import GRUPE, ZILE_RO, Profil, Programare, Sablon, Setari, ZiInchisa


def export_saptamana_response(luni: date):
    """Foaie Excel pe săptămână (luni–sâmbătă), în formatul foii de lucru actuale."""
    setari = Setari.get()
    wb = Workbook()
    ws = wb.active
    ws.title = f'Sapt {luni:%d.%m}-{luni + timedelta(days=5):%d.%m}'
    bold = Font(bold=True)
    banda = PatternFill('solid', fgColor='EEF2FF')
    r = 1
    for zi_idx in range(6):
        zi = luni + timedelta(days=zi_idx)
        sabloane = list(Sablon.objects.filter(activ=True, zi=zi.weekday()))
        if not sabloane:
            continue
        ws.cell(r, 1, f'{ZILE_RO[zi.weekday()]} {zi:%d.%m.%Y}').font = bold
        r += 1
        for s in sabloane:
            ws.cell(r, 1, f'{s.ora_start:%H:%M}–{s.ora_sfarsit:%H:%M}').font = bold
            for c, t in enumerate(['Nr.', 'Copil', 'Vârstă', 'Părinte', 'Telefon', 'Observații'], start=2):
                cell = ws.cell(r, c, t)
                cell.font = bold
                cell.fill = banda
            r += 1
            progs = list(Programare.objects.filter(data=zi, sablon=s).exclude(status='anulat'))
            for grupa, eticheta in GRUPE:
                ws.cell(r, 1, f'Nivel: {eticheta}').font = bold
                r += 1
                de_grupa = [p for p in progs if p.grupa == grupa]
                for n in range(setari.locuri(grupa)):
                    p = de_grupa[n] if n < len(de_grupa) else None
                    ws.cell(r, 2, n + 1)
                    if p:
                        valori = [p.nume_copil, p.varsta, p.nume_parinte, p.telefon, p.observatii]
                        for c, v in enumerate(valori, start=3):
                            ws.cell(r, c, v)
                    r += 1
            r += 1
    for col, w in zip('ABCDEFG', (24, 6, 28, 8, 26, 16, 30)):
        ws.column_dimensions[col].width = w
    resp = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="programari_inot_{luni:%Y-%m-%d}.xlsx"'
    wb.save(resp)
    return resp


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
