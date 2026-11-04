from datetime import datetime

from django.db import models

ZILE_RO = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

GRUPA_INITIERE = 'initiere'
GRUPA_PERF = 'perfectionare'
GRUPE = [(GRUPA_INITIERE, 'Inițiere (3–6 ani)'), (GRUPA_PERF, 'Perfecționare (7+ ani)')]


def determina_grupa(varsta: int, avansat: bool) -> str:
    """Începători sau sub 7 ani -> inițiere; avansați cu minim 7 ani -> perfecționare."""
    if varsta < 7 or not avansat:
        return GRUPA_INITIERE
    return GRUPA_PERF


class Setari(models.Model):
    """Rând unic cu setările generale."""
    locuri_initiere = models.PositiveSmallIntegerField(default=7)
    locuri_perfectionare = models.PositiveSmallIntegerField(default=7)
    saptamani_in_avans = models.PositiveSmallIntegerField(
        default=2, help_text='Cu câte săptămâni în avans se pot face programări')
    ore_inchidere = models.PositiveSmallIntegerField(
        default=2, help_text='Programările se închid cu atâtea ore înainte de începerea ședinței')
    mesaj_confirmare = models.TextField(
        blank=True, help_text='Text adăugat în emailul de confirmare (adresă, ce să aducă etc.)')

    class Meta:
        verbose_name = 'Setări'
        verbose_name_plural = 'Setări'

    def __str__(self):
        return 'Setări înot'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def locuri(self, grupa):
        return self.locuri_initiere if grupa == GRUPA_INITIERE else self.locuri_perfectionare


class Sablon(models.Model):
    """O ședință care se repetă săptămânal (ex.: luni 17:00)."""
    zi = models.PositiveSmallIntegerField(choices=list(enumerate(ZILE_RO)))
    ora_start = models.TimeField()
    ora_sfarsit = models.TimeField()
    activ = models.BooleanField(default=True)

    class Meta:
        ordering = ['zi', 'ora_start']
        verbose_name = 'Interval săptămânal'
        verbose_name_plural = 'Orar săptămânal'
        unique_together = [('zi', 'ora_start')]

    def __str__(self):
        return f'{ZILE_RO[self.zi]} {self.ora_start:%H:%M}–{self.ora_sfarsit:%H:%M}'


class ZiInchisa(models.Model):
    """Zi în care nu se fac ședințe (sărbători, închis etc.)."""
    data = models.DateField(unique=True)
    motiv = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ['data']
        verbose_name = 'Zi închisă'
        verbose_name_plural = 'Zile închise'

    def __str__(self):
        return f'{self.data:%d.%m.%Y} {self.motiv}'.strip()


class Programare(models.Model):
    STATUS = [('confirmat', 'Confirmat'), ('anulat', 'Anulat'), ('prezent', 'Prezent')]

    sablon = models.ForeignKey(Sablon, on_delete=models.PROTECT, related_name='programari')
    data = models.DateField()
    grupa = models.CharField(max_length=20, choices=GRUPE)
    nume_copil = models.CharField(max_length=100)
    varsta = models.PositiveSmallIntegerField()
    avansat = models.BooleanField(default=False, help_text='Copilul știe deja să înoate')
    nume_parinte = models.CharField(max_length=100)
    telefon = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    observatii = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='confirmat')
    creat_la = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data', 'sablon__ora_start', 'grupa', 'creat_la']
        verbose_name = 'Programare'
        verbose_name_plural = 'Programări'
        indexes = [models.Index(fields=['data', 'sablon', 'grupa'])]

    def __str__(self):
        return f'{self.nume_copil} — {self.data:%d.%m.%Y} {self.sablon.ora_start:%H:%M}'
