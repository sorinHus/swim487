from datetime import time

from django.core.management.base import BaseCommand

from inot.models import Sablon, Setari


class Command(BaseCommand):
    help = 'Creează setările și orarul implicit (luni–vineri 17:00 și 18:00, sâmbătă 10:00 și 11:00).'

    def handle(self, *args, **options):
        Setari.get()
        sloturi = [(z, time(h), time(h + 1)) for z in range(5) for h in (17, 18)]
        sloturi += [(5, time(10), time(11)), (5, time(11), time(12))]
        creat = 0
        for zi, start, sfarsit in sloturi:
            _, nou = Sablon.objects.get_or_create(zi=zi, ora_start=start, defaults={'ora_sfarsit': sfarsit})
            creat += nou
        self.stdout.write(self.style.SUCCESS(f'Orar gata ({creat} intervale noi).'))
