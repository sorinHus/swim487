"""Logica de disponibilitate: ședințele se generează din orarul săptămânal."""
from collections import Counter
from datetime import date, datetime, timedelta

from django.utils import timezone

from .models import (GRUPA_INITIERE, GRUPA_PERF, Programare, Sablon, Setari,
                     ZiInchisa, ZILE_RO)


def _acum_local():
    return timezone.localtime(timezone.now()).replace(tzinfo=None)


def sedinte_disponibile(de_la: date | None = None):
    """Lista ședințelor rezervabile, cu locurile rămase pe fiecare grupă."""
    setari = Setari.get()
    acum = _acum_local()
    azi = acum.date()
    de_la = max(de_la or azi, azi)
    pana_la = azi + timedelta(weeks=setari.saptamani_in_avans, days=(6 - azi.weekday()))

    sabloane = list(Sablon.objects.filter(activ=True))
    inchise = set(ZiInchisa.objects.filter(data__range=(de_la, pana_la)).values_list('data', flat=True))
    ocupate = Counter(
        Programare.objects.filter(data__range=(de_la, pana_la))
        .exclude(status='anulat').values_list('sablon_id', 'data', 'grupa')
    )

    rezultat = []
    zi = de_la
    while zi <= pana_la:
        if zi not in inchise:
            for s in sabloane:
                if s.zi != zi.weekday():
                    continue
                start = datetime.combine(zi, s.ora_start)
                if start - acum < timedelta(hours=setari.ore_inchidere):
                    continue
                rezultat.append({
                    'sablon': s.id,
                    'data': zi.isoformat(),
                    'zi': ZILE_RO[zi.weekday()],
                    'ora_start': s.ora_start.strftime('%H:%M'),
                    'ora_sfarsit': s.ora_sfarsit.strftime('%H:%M'),
                    'locuri': {
                        g: max(0, setari.locuri(g) - ocupate.get((s.id, zi, g), 0))
                        for g in (GRUPA_INITIERE, GRUPA_PERF)
                    },
                })
        zi += timedelta(days=1)
    rezultat.sort(key=lambda r: (r['data'], r['ora_start']))
    return rezultat
