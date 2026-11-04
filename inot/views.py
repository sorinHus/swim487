import logging
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django_ratelimit.decorators import ratelimit
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .admin import export_saptamana_response
from .auth import EsteInstructor, EsteSuperadmin, token_pentru
from .models import GRUPE, ZILE_RO, Profil, Programare, Setari, determina_grupa
from .services import EroareProgramare, se_poate_modifica, sedinte_disponibile, verifica_loc

log = logging.getLogger(__name__)
User = get_user_model()


def client_ip(group, request):
    """IP-ul vizitatorului; în spatele proxy-ului Railway vine în X-Forwarded-For."""
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return fwd.split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')


def limiteaza(rate):
    return method_decorator(ratelimit(key=client_ip, rate=rate, method='POST', block=True), name='post')


def trimite(subiect, mesaj, catre):
    try:
        send_mail(subject=subiect, message=mesaj, from_email=settings.DEFAULT_FROM_EMAIL,
                  recipient_list=[catre], fail_silently=False)
    except Exception:
        log.exception('Eroare email catre %s', catre)


def cand(p):
    return f'{ZILE_RO[p.data.weekday()]} {p.data:%d.%m.%Y}, ora {p.sablon.ora_start:%H:%M}'


# ---------- Disponibilitate (public) ----------

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
            'ore_anulare': setari.ore_anulare,
        })


# ---------- Cont ----------

def date_cont(user):
    profil = getattr(user, 'profil', None)
    return {
        'email': user.email,
        'nume': profil.nume if profil else '',
        'telefon': profil.telefon if profil else '',
        'instructor': user.is_staff or user.is_superuser,
        'superadmin': user.is_superuser,
    }


def raspuns_auth(user):
    return Response({'token': token_pentru(user), 'cont': date_cont(user)})


class ProfilSerializer(serializers.Serializer):
    nume = serializers.CharField(max_length=100)
    telefon = serializers.RegexField(r'^[0-9+ ().-]{7,20}$', max_length=20)


class InregistrareSerializer(ProfilSerializer):
    email = serializers.EmailField(max_length=150)
    parola = serializers.CharField(max_length=128, write_only=True)


def eroare_parola(parola, user):
    try:
        validate_password(parola, user)
    except DjangoValidationError as e:
        raise ValidationError({'detail': ' '.join(e.messages)})


@limiteaza('10/h')
class InregistrareView(APIView):
    authentication_classes = []

    def post(self, request):
        ser = InregistrareSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        email = d['email'].strip().lower()
        deja = ValidationError({'detail': 'Există deja un cont cu acest email. Autentifică-te.'})
        if User.objects.filter(username__iexact=email).exists():
            raise deja
        eroare_parola(d['parola'], User(username=email, email=email))
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=email, email=email, password=d['parola'])
                Profil.objects.create(user=user, nume=d['nume'].strip(), telefon=d['telefon'])
        except IntegrityError:
            raise deja
        return raspuns_auth(user)


@limiteaza('30/h')
class AutentificareView(APIView):
    authentication_classes = []

    def post(self, request):
        ident = str(request.data.get('email', '')).strip()
        parola = str(request.data.get('parola', ''))
        # Acceptă emailul sau username-ul (conturile create din admin pot avea alt username)
        cont = (User.objects.filter(username__iexact=ident).first()
                or User.objects.filter(email__iexact=ident).order_by('id').first())
        user = authenticate(request, username=cont.username, password=parola) if cont else None
        if user is None:
            return Response({'detail': 'Email sau parolă greșită.'}, status=status.HTTP_400_BAD_REQUEST)
        return raspuns_auth(user)


class IesireView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(date_cont(request.user))

    def patch(self, request):
        ser = ProfilSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        Profil.objects.update_or_create(
            user=request.user,
            defaults={'nume': ser.validated_data['nume'].strip(), 'telefon': ser.validated_data['telefon']})
        request.user.refresh_from_db()
        return Response(date_cont(request.user))


def link_resetare(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f'{settings.FRONTEND_URL}#/reset/{uid}/{default_token_generator.make_token(user)}'


@limiteaza('5/h')
class ResetareCerereView(APIView):
    """Trimite linkul de resetare; răspunsul e mereu același, ca să nu dezvăluim ce emailuri au cont."""
    authentication_classes = []

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        user = User.objects.filter(username__iexact=email, is_active=True).first()
        if user:
            link = link_resetare(user)
            trimite('Resetare parolă — programări înot',
                    f'Ai cerut resetarea parolei. Deschide linkul (valabil câteva ore):\n\n{link}\n\n'
                    f'Dacă nu ai cerut tu, ignoră acest mesaj.', user.email)
        return Response({'detail': 'Dacă există un cont cu acest email, ți-am trimis un link de resetare.'})


@limiteaza('10/h')
class ResetareConfirmaView(APIView):
    authentication_classes = []

    def post(self, request):
        invalid = ValidationError({'detail': 'Linkul de resetare nu este valid sau a expirat.'})
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(str(request.data.get('uid', '')))))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise invalid
        if not default_token_generator.check_token(user, str(request.data.get('token', ''))):
            raise invalid
        parola = str(request.data.get('parola', ''))
        eroare_parola(parola, user)
        user.set_password(parola)
        user.save()
        Token.objects.filter(user=user).delete()
        return raspuns_auth(user)


# ---------- Programări (părinte) ----------

class ProgramareInSerializer(serializers.Serializer):
    sablon = serializers.IntegerField()
    data = serializers.DateField()
    nume_copil = serializers.CharField(max_length=100)
    varsta = serializers.IntegerField(min_value=3, max_value=18)
    avansat = serializers.BooleanField(default=False)
    observatii = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    # Doar pentru staff: id-ul contului de părinte al copilului (din căutarea de copii)
    cont = serializers.IntegerField(required=False)


def ser_programare(p, setari):
    return {
        'id': p.id,
        'data': p.data.isoformat(),
        'zi': ZILE_RO[p.data.weekday()],
        'sablon': p.sablon_id,
        'ora_start': p.sablon.ora_start.strftime('%H:%M'),
        'ora_sfarsit': p.sablon.ora_sfarsit.strftime('%H:%M'),
        'grupa': p.grupa,
        'nume_copil': p.nume_copil,
        'varsta': p.varsta,
        'avansat': p.avansat,
        'observatii': p.observatii,
        'status': p.status,
        'modificabil': se_poate_modifica(p, setari),
    }


def raspuns_eroare(e: EroareProgramare):
    return Response({'detail': e.mesaj}, status=e.cod)


class ProgrameazaView(APIView):
    permission_classes = [IsAuthenticated]

    @method_decorator(ratelimit(key='user', rate='30/h', method='POST', block=True))
    def post(self, request):
        ser = ProgramareInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        grupa = determina_grupa(d['varsta'], d['avansat'])
        if request.user.is_staff or request.user.is_superuser:
            # Instructor/superadmin programează un copil existent: programarea se leagă de contul părintelui
            proprietar = User.objects.filter(pk=d.get('cont'), is_active=True, is_staff=False,
                                             is_superuser=False).select_related('profil').first()
            if proprietar is None:
                raise ValidationError({'detail': 'Alege copilul din căutare.'})
        else:
            proprietar = request.user
        profil = getattr(proprietar, 'profil', None)
        if profil is None:
            return Response({'detail': 'Completează numele și telefonul în contul tău.'}, status=400)
        nume_parinte, telefon, email = profil.nume, profil.telefon, proprietar.email

        try:
            with transaction.atomic():
                # Blocăm rândul setărilor ca două cereri simultane să nu depășească locurile
                Setari.objects.get_or_create(pk=1)
                setari = Setari.objects.select_for_update().get(pk=1)
                verifica_loc(d['sablon'], d['data'], grupa)
                duplicat = Programare.objects.filter(
                    sablon_id=d['sablon'], data=d['data'], nume_copil__iexact=d['nume_copil'], user=proprietar
                ).exclude(status='anulat').exists()
                if duplicat:
                    raise EroareProgramare('Copilul este deja programat la această oră.')
                p = Programare.objects.create(
                    user=proprietar, grupa=grupa, sablon_id=d['sablon'], data=d['data'],
                    nume_copil=d['nume_copil'], varsta=d['varsta'], avansat=d['avansat'],
                    observatii=d['observatii'], nume_parinte=nume_parinte, telefon=telefon,
                    email=email)
        except EroareProgramare as e:
            return raspuns_eroare(e)

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
        if p.email:
            trimite('Confirmare programare înot',
                    f'Bună ziua, {p.nume_parinte},\n\n'
                    f'Programarea pentru {p.nume_copil} a fost înregistrată:\n'
                    f'  Când:  {cand(p)}\n  Grupa: {grupa}\n\n'
                    f'{setari.mesaj_confirmare}\n\n'
                    f'Poți anula sau reprograma din contul tău, cu cel puțin {setari.ore_anulare} de ore înainte.',
                    p.email)
        if settings.EMAIL_ADMIN:
            trimite(f'Programare înot nouă — {p.nume_copil} — {cand(p)}',
                    f'Copil: {p.nume_copil} ({p.varsta} ani, {"avansat" if p.avansat else "începător"})\n'
                    f'Grupa: {grupa}\nCând: {cand(p)}\n'
                    f'Părinte: {p.nume_parinte}\nTelefon: {p.telefon}\nEmail: {p.email or "—"}\n'
                    f'Observații: {p.observatii or "—"}', settings.EMAIL_ADMIN)


class ProgramarileMeleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        setari = Setari.get()
        qs = Programare.objects.filter(user=request.user).select_related('sablon').order_by('-data', 'sablon__ora_start')
        return Response([ser_programare(p, setari) for p in qs])


class ProgramareParinteView(APIView):
    """Baza pentru anulare/reprogramare: blochează rândul și verifică regula orelor."""
    permission_classes = [IsAuthenticated]

    def _blocheaza(self, request, pk):
        Setari.objects.get_or_create(pk=1)
        setari = Setari.objects.select_for_update().get(pk=1)
        try:
            p = Programare.objects.select_related('sablon').get(pk=pk, user=request.user)
        except Programare.DoesNotExist:
            raise NotFound('Programarea nu există.')
        if p.status != 'confirmat':
            raise EroareProgramare('Programarea nu mai este activă.')
        if not se_poate_modifica(p, setari):
            raise EroareProgramare(
                f'Programarea se poate modifica doar cu cel puțin {setari.ore_anulare} de ore înainte. '
                f'Te rugăm să ne contactezi telefonic.', 403)
        return p, setari


class AnuleazaView(ProgramareParinteView):
    def post(self, request, pk):
        try:
            with transaction.atomic():
                p, setari = self._blocheaza(request, pk)
                p.status = 'anulat'
                p.save(update_fields=['status'])
        except EroareProgramare as e:
            return raspuns_eroare(e)
        trimite('Programare înot anulată', f'Programarea pentru {p.nume_copil} ({cand(p)}) a fost anulată.', p.email)
        if settings.EMAIL_ADMIN:
            trimite(f'Programare anulată — {p.nume_copil} — {cand(p)}',
                    f'Părinte: {p.nume_parinte}, tel. {p.telefon}', settings.EMAIL_ADMIN)
        return Response(ser_programare(p, setari))


class ReprogrameazaView(ProgramareParinteView):
    def post(self, request, pk):
        try:
            sablon = int(request.data.get('sablon'))
            data = date.fromisoformat(str(request.data.get('data')))
        except (TypeError, ValueError):
            return Response({'detail': 'Alege noua ședință.'}, status=400)
        try:
            with transaction.atomic():
                p, setari = self._blocheaza(request, pk)
                if (p.sablon_id, p.data) == (sablon, data):
                    raise EroareProgramare('Ai ales aceeași ședință.')
                vechi = cand(p)
                verifica_loc(sablon, data, p.grupa)
                p.sablon_id, p.data = sablon, data
                p.save(update_fields=['sablon', 'data'])
                p = Programare.objects.select_related('sablon').get(pk=p.pk)
        except EroareProgramare as e:
            return raspuns_eroare(e)
        trimite('Programare înot reprogramată',
                f'Programarea pentru {p.nume_copil} a fost mutată din {vechi} în {cand(p)}.', p.email)
        if settings.EMAIL_ADMIN:
            trimite(f'Programare reprogramată — {p.nume_copil} — {cand(p)}',
                    f'Mutată din {vechi}. Părinte: {p.nume_parinte}, tel. {p.telefon}', settings.EMAIL_ADMIN)
        return Response(ser_programare(p, setari))


# ---------- Instructor ----------

def ser_instructor(p):
    return {
        'id': p.id,
        'sablon': p.sablon_id,
        'ora_start': p.sablon.ora_start.strftime('%H:%M'),
        'ora_sfarsit': p.sablon.ora_sfarsit.strftime('%H:%M'),
        'grupa': p.grupa,
        'nume_copil': p.nume_copil,
        'varsta': p.varsta,
        'avansat': p.avansat,
        'nume_parinte': p.nume_parinte,
        'telefon': p.telefon,
        'observatii': p.observatii,
        'status': p.status,
    }


def data_din_query(request, cheie='data'):
    try:
        return date.fromisoformat(request.query_params[cheie]) if cheie in request.query_params else date.today()
    except ValueError:
        raise ValidationError({'detail': 'Dată invalidă.'})


class InstructorZiView(APIView):
    permission_classes = [EsteInstructor]

    def get(self, request):
        zi = data_din_query(request)
        qs = Programare.objects.filter(data=zi).select_related('sablon').order_by('sablon__ora_start', 'grupa', 'creat_la')
        return Response({'data': zi.isoformat(), 'zi': ZILE_RO[zi.weekday()],
                         'programari': [ser_instructor(p) for p in qs]})


class InstructorProgramareView(APIView):
    permission_classes = [EsteInstructor]

    def patch(self, request, pk):
        nou = request.data.get('status')
        if nou not in ('confirmat', 'anulat', 'prezent'):
            return Response({'detail': 'Status invalid.'}, status=400)
        try:
            with transaction.atomic():
                Setari.objects.get_or_create(pk=1)
                Setari.objects.select_for_update().get(pk=1)
                try:
                    p = Programare.objects.select_related('sablon').get(pk=pk)
                except Programare.DoesNotExist:
                    raise NotFound('Programarea nu există.')
                if p.status == 'anulat' and nou != 'anulat':
                    # Repunerea unei programări anulate nu are voie să depășească locurile grupei
                    verifica_loc(p.sablon_id, p.data, p.grupa)
                p.status = nou
                p.save(update_fields=['status'])
        except EroareProgramare as e:
            return raspuns_eroare(e)
        return Response(ser_instructor(p))


class InstructorCopiiView(APIView):
    """Căutare de copii (din programările conturilor de părinți) pentru a programa la cererea părinților."""
    permission_classes = [EsteInstructor]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response([])
        qs = (Programare.objects.filter(user__isnull=False, user__is_staff=False, user__is_superuser=False,
                                        user__is_active=True)
              .filter(Q(nume_copil__icontains=q) | Q(nume_parinte__icontains=q) | Q(telefon__icontains=q))
              .order_by('-creat_la'))
        copii = {}
        for p in qs[:300]:
            copii.setdefault((p.user_id, p.nume_copil.strip().lower()), p)  # cea mai recentă programare a fiecărui copil
        rezultat = [{'cont': p.user_id, 'nume_copil': p.nume_copil, 'varsta': p.varsta, 'avansat': p.avansat,
                     'nume_parinte': p.nume_parinte, 'telefon': p.telefon}
                    for p in list(copii.values())[:15]]
        return Response(sorted(rezultat, key=lambda c: (c['nume_copil'].lower(), c['nume_parinte'].lower())))


class InstructorExportView(APIView):
    permission_classes = [EsteInstructor]

    def get(self, request):
        zi = data_din_query(request, 'luni')
        return export_saptamana_response(zi - timedelta(days=zi.weekday()))


# ---------- Superadmin: conturi de instructori ----------

def ser_instructor_cont(u):
    profil = getattr(u, 'profil', None)
    return {'id': u.id, 'email': u.email, 'nume': profil.nume if profil else '', 'activ': u.is_active}


class InstructoriView(APIView):
    permission_classes = [EsteSuperadmin]

    def get(self, request):
        qs = User.objects.filter(is_staff=True, is_superuser=False).select_related('profil').order_by('email')
        return Response([ser_instructor_cont(u) for u in qs])

    @method_decorator(ratelimit(key='user', rate='30/h', method='POST', block=True))
    def post(self, request):
        """Creează un instructor (sau promovează un cont de părinte existent) și îi trimite linkul de setare a parolei."""
        email = str(request.data.get('email', '')).strip().lower()
        nume = str(request.data.get('nume', '')).strip()[:100]
        try:
            serializers.EmailField(max_length=150).run_validation(email)
        except serializers.ValidationError:
            raise ValidationError({'detail': 'Email invalid.'})
        if not nume:
            raise ValidationError({'detail': 'Completează numele instructorului.'})
        user = User.objects.filter(username__iexact=email).first()
        if user is None:
            user = User(username=email, email=email)
            user.set_unusable_password()
        elif user.is_superuser:
            raise ValidationError({'detail': 'Contul este deja superadmin.'})
        user.is_staff, user.is_active = True, True
        user.save()
        Profil.objects.get_or_create(user=user, defaults={'nume': nume, 'telefon': ''})
        trimite('Cont instructor — programări înot',
                f'Bună, {nume},\n\nAi primit acces de instructor la programările de înot.\n'
                f'Setează-ți parola aici, apoi autentifică-te:\n\n{link_resetare(user)}',
                user.email)
        return Response(ser_instructor_cont(user), status=status.HTTP_201_CREATED)


class InstructorContView(APIView):
    permission_classes = [EsteSuperadmin]

    def _get(self, pk):
        try:
            return User.objects.select_related('profil').get(pk=pk, is_staff=True, is_superuser=False)
        except User.DoesNotExist:
            raise NotFound('Instructorul nu există.')

    def patch(self, request, pk):
        u = self._get(pk)
        u.is_active = bool(request.data.get('activ'))
        u.save(update_fields=['is_active'])
        if not u.is_active:
            Token.objects.filter(user=u).delete()
        return Response(ser_instructor_cont(u))

    def delete(self, request, pk):
        """Retrage rolul de instructor (contul rămâne, ca simplu cont de părinte)."""
        u = self._get(pk)
        u.is_staff = False
        u.save(update_fields=['is_staff'])
        return Response(status=status.HTTP_204_NO_CONTENT)
