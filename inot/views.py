import logging
from datetime import date

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import GRUPE, ZILE_RO, Programare, Setari, determina_grupa
from .services import sedinte_disponibile

log = logging.getLogger(__name__)


def client_ip(group, request):
    """IP-ul vizitatorului; în spatele proxy-ului Railway vine în X-Forwarded-For."""
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return fwd.split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')


class DisponibilitateView(APIView):
    def get(self, request):
        try:
            de_la = date.fromisoformat(request.query_params['de_la']) if 'de_la' in request.query_params else None
        except ValueError:
            return Response({'detail': 'Dată invalidă.'}, status=400)
        setari = Setari.get()
        return Response({
            'sedinte': sedinte_disponibile(de_la),
            'locuri_pe_grupa': {'initiere': setari.locuri_initiere, 'perfectionare': setari.locuri_perfectionare},
        })


class ProgramareInSerializer(serializers.Serializer):
    sablon = serializers.IntegerField()
    data = serializers.DateField()
    nume_copil = serializers.CharField(max_length=100)
    varsta = serializers.IntegerField(min_value=3, max_value=18)
    avansat = serializers.BooleanField(default=False)
    nume_parinte = serializers.CharField(max_length=100)
    telefon = serializers.RegexField(r'^[0-9+ ().-]{7,20}$', max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    observatii = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


@method_decorator(ratelimit(key=client_ip, rate='10/h', method='POST', block=True), name='post')
class ProgrameazaView(APIView):
    def post(self, request):
        ser = ProgramareInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        grupa = determina_grupa(d['varsta'], d['avansat'])

        with transaction.atomic():
            # Blocăm rândul setărilor ca două cereri simultane să nu depășească locurile
            Setari.objects.get_or_create(pk=1)
            setari = Setari.objects.select_for_update().get(pk=1)
            liber = next(
                (s for s in sedinte_disponibile(d['data'])
                 if s['sablon'] == d['sablon'] and s['data'] == d['data'].isoformat()),
                None,
            )
            if liber is None:
                return Response({'detail': 'Ședința nu mai este disponibilă.'}, status=status.HTTP_409_CONFLICT)
            if liber['locuri'][grupa] <= 0:
                return Response({'detail': 'Nu mai sunt locuri în această grupă la această oră.'},
                                status=status.HTTP_409_CONFLICT)
            duplicat = Programare.objects.filter(
                sablon_id=d['sablon'], data=d['data'], nume_copil__iexact=d['nume_copil'], telefon=d['telefon']
            ).exclude(status='anulat').exists()
            if duplicat:
                return Response({'detail': 'Copilul este deja programat la această oră.'},
                                status=status.HTTP_409_CONFLICT)
            date_p = {k: v for k, v in d.items() if k != 'sablon'}
            p = Programare.objects.create(grupa=grupa, sablon_id=d['sablon'], **date_p)

        self._emailuri(p, setari)
        return Response({
            'id': p.id,
            'grupa': grupa,
            'data': p.data.isoformat(),
            'zi': ZILE_RO[p.data.weekday()],
            'ora_start': p.sablon.ora_start.strftime('%H:%M'),
        }, status=status.HTTP_201_CREATED)

    def _emailuri(self, p, setari):
        grupa = dict(GRUPE)[p.grupa]
        cand = f'{ZILE_RO[p.data.weekday()]} {p.data:%d.%m.%Y}, ora {p.sablon.ora_start:%H:%M}'
        try:
            if p.email:
                send_mail(
                    subject='Confirmare programare înot',
                    message=(f'Bună ziua, {p.nume_parinte},\n\n'
                             f'Programarea pentru {p.nume_copil} a fost înregistrată:\n'
                             f'  Când:  {cand}\n  Grupa: {grupa}\n\n'
                             f'{setari.mesaj_confirmare}\n\n'
                             f'Dacă nu puteți ajunge, vă rugăm să ne anunțați.'),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[p.email],
                    fail_silently=False,
                )
        except Exception:
            log.exception('Eroare email catre parinte')
        try:
            if settings.EMAIL_ADMIN:
                send_mail(
                    subject=f'Programare înot nouă — {p.nume_copil} — {cand}',
                    message=(f'Copil: {p.nume_copil} ({p.varsta} ani, {"avansat" if p.avansat else "începător"})\n'
                             f'Grupa: {grupa}\nCând: {cand}\n'
                             f'Părinte: {p.nume_parinte}\nTelefon: {p.telefon}\nEmail: {p.email or "—"}\n'
                             f'Observații: {p.observatii or "—"}'),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.EMAIL_ADMIN],
                    fail_silently=False,
                )
        except Exception:
            log.exception('Eroare email catre admin')
