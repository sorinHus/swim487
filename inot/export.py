"""Export Excel pe săptămână, în formatul foii de lucru `programari_inot.xlsx`:
zile două câte două pe rând (luni+marți, miercuri+joi, vineri+sâmbătă), orele pe coloane,
nivelurile pe rânduri numerotate continuu (inițiere 1–7, perfecționare 8–14)."""
from datetime import date, timedelta

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import GRUPA_INITIERE, GRUPA_PERF, Programare, Sablon, Setari

NOTA = ('Copiii începători sau cu vârsta sub 7 ani vor fi încadrați în grupa de inițiere, iar copiii mai avansați '
        'sau cu vârsta de minimum 7 ani vor fi încadrați în grupa de consolidare (perfecționare).')
ETICHETE = {GRUPA_INITIERE: 'Nivel: inițiere / 3-6 ani', GRUPA_PERF: 'Nivel: perf / 7+ ani'}

FILL_ANTET = PatternFill('solid', fgColor='9FC5E8')
FILL_NR = PatternFill('solid', fgColor='B4A7D6')
FIR = Side(style='thin')
MARGINI = Border(left=FIR, right=FIR, top=FIR, bottom=FIR)
CENTRU = Alignment(horizontal='center', vertical='center', wrap_text=True)
ZI_RO_FORMAT = 'dddd\\ dd\\.mm'  # Excel îl afișează în limba sistemului utilizatorului


def _scrie_zi(ws, rand, col, zi, sabloane, programari, locuri, latime):
    """Desenează o zi: antet cu ore, apoi rândurile de nume pe niveluri. `col` = coloana A a zilei."""
    ws.cell(rand, col + 2, None)
    for k, s in enumerate(sabloane):
        c = ws.cell(rand, col + 2 + k, 'Nume')
        c.alignment = CENTRU

    antet = rand + 1
    for c_idx in range(col, col + 2 + latime):
        c = ws.cell(antet, c_idx)
        c.fill, c.border, c.alignment = FILL_ANTET, MARGINI, CENTRU
        c.font = Font(bold=True)
    ws.cell(antet, col, zi).number_format = ZI_RO_FORMAT
    for k, s in enumerate(sabloane):
        ws.cell(antet, col + 2 + k, s.ora_start).number_format = 'hh:mm'

    r = antet + 1
    nr = 1
    for grupa in (GRUPA_INITIERE, GRUPA_PERF):
        inceput = r
        for n in range(locuri[grupa]):
            a = ws.cell(r, col, nr)
            a.fill, a.border, a.alignment = FILL_NR, MARGINI, CENTRU
            ws.cell(r, col + 1).border = MARGINI
            for k, s in enumerate(sabloane):
                cel = ws.cell(r, col + 2 + k)
                cel.border = MARGINI
                lista = programari.get((s.id, grupa), [])
                if n < len(lista):
                    cel.value = lista[n].nume_copil
            r += 1
            nr += 1
        ws.merge_cells(start_row=inceput, start_column=col + 1, end_row=r - 1, end_column=col + 1)
        eticheta = ws.cell(inceput, col + 1, ETICHETE[grupa])
        eticheta.font, eticheta.alignment, eticheta.border = Font(bold=True), Alignment(
            horizontal='center', vertical='center', text_rotation=90, wrap_text=True), MARGINI
    return r


def export_saptamana_response(luni: date):
    setari = Setari.get()
    locuri = {GRUPA_INITIERE: setari.locuri_initiere, GRUPA_PERF: setari.locuri_perfectionare}
    sabloane = {z: list(Sablon.objects.filter(activ=True, zi=z).order_by('ora_start')) for z in range(6)}
    latime = max(2, max(len(v) for v in sabloane.values()))  # câte coloane de ore are o zi

    programari = {}
    qs = (Programare.objects.filter(data__range=(luni, luni + timedelta(days=5))).exclude(status='anulat')
          .order_by('creat_la'))
    for p in qs:
        programari.setdefault((p.data, p.sablon_id, p.grupa), []).append(p)

    wb = Workbook()
    ws = wb.active
    ws.title = f'Sapt {luni:%d.%m}-{luni + timedelta(days=5):%d.%m}'

    # Lățimi ca în foaia originală: dată 16, nivel 5, ore ~21.5; două coloane libere între zile
    stanga = 1
    dreapta = stanga + 2 + latime + 2
    for start in (stanga, dreapta):
        ws.column_dimensions[get_column_letter(start)].width = 16.3
        ws.column_dimensions[get_column_letter(start + 1)].width = 4.8
        for k in range(latime):
            ws.column_dimensions[get_column_letter(start + 2 + k)].width = 21.5

    ws.merge_cells(start_row=1, start_column=3, end_row=2, end_column=dreapta + 1 + latime)
    ws['C1'] = NOTA
    ws['C1'].alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
    ws.merge_cells('A1:B1')

    r = 5
    for pereche in ((0, 1), (2, 3), (4, 5)):
        sfarsit = r
        for col, zi_idx in zip((stanga, dreapta), pereche):
            zi = luni + timedelta(days=zi_idx)
            prog_zi = {(s.id, g): programari.get((zi, s.id, g), []) for s in sabloane[zi_idx] for g in locuri}
            sfarsit = max(sfarsit, _scrie_zi(ws, r, col, zi, sabloane[zi_idx], prog_zi, locuri, latime))
        r = sfarsit + 2  # două rânduri libere între perechi de zile
    for rand in range(5, r):
        ws.row_dimensions[rand].height = 21

    resp = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="programari_inot_{luni:%Y-%m-%d}.xlsx"'
    wb.save(resp)
    return resp
