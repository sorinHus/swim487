from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Profil, Programare, Sablon, Setari

User = get_user_model()
PAROLA = 'parola-Sigura-93'


def urmatoarea_data(zile_min):
    """Prima zi (luni–sâmbătă) la cel puțin `zile_min` zile de acum."""
    d = timezone.localtime(timezone.now()).date() + timedelta(days=zile_min)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


@override_settings(FRONTEND_URL='https://exemplu.test/inot/', EMAIL_ADMIN='')
class BazaTest(TestCase):
    def setUp(self):
        cache.clear()
        Setari.get()
        self.c = APIClient()
        self.sabloane = {z: Sablon.objects.create(zi=z, ora_start=time(17), ora_sfarsit=time(18)) for z in range(6)}

    def sablon_pe(self, data):
        return self.sabloane[data.weekday()]

    def inregistreaza(self, email='ana@test.ro'):
        r = self.c.post('/api/inot/auth/register/', {
            'email': email, 'parola': PAROLA, 'nume': 'Ana Pop', 'telefon': '0712345678'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.c.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])
        return r.json()

    def programeaza(self, data, nume='Mihai', varsta=8, avansat=True):
        return self.c.post('/api/inot/programeaza/', {
            'sablon': self.sablon_pe(data).id, 'data': data.isoformat(),
            'nume_copil': nume, 'varsta': varsta, 'avansat': avansat}, format='json')


class ContTest(BazaTest):
    def test_programare_fara_cont_refuzata(self):
        d = urmatoarea_data(5)
        self.assertEqual(self.programeaza(d).status_code, 401)

    def test_calendarul_ramane_public(self):
        self.assertEqual(self.c.get('/api/inot/disponibil/').status_code, 200)

    def test_inregistrare_si_login(self):
        j = self.inregistreaza()
        self.assertEqual(j['cont']['email'], 'ana@test.ro')
        self.assertFalse(j['cont']['instructor'])
        c2 = APIClient()
        r = c2.post('/api/inot/auth/login/', {'email': 'ANA@test.ro', 'parola': PAROLA}, format='json')
        self.assertEqual(r.status_code, 200)
        r = c2.post('/api/inot/auth/login/', {'email': 'ana@test.ro', 'parola': 'gresita'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_email_duplicat_si_parola_slaba(self):
        self.inregistreaza()
        r = APIClient().post('/api/inot/auth/register/', {
            'email': 'Ana@test.ro', 'parola': PAROLA, 'nume': 'X', 'telefon': '0712345678'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = APIClient().post('/api/inot/auth/register/', {
            'email': 'b@test.ro', 'parola': '12345678', 'nume': 'X', 'telefon': '0712345678'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_token_expirat(self):
        self.inregistreaza()
        Token.objects.update(created=timezone.now() - timedelta(days=31))
        self.assertEqual(self.c.get('/api/inot/cont/').status_code, 401)
        self.assertFalse(Token.objects.exists())

    def test_logout_sterge_tokenul(self):
        self.inregistreaza()
        self.assertEqual(self.c.post('/api/inot/auth/logout/').status_code, 204)
        self.assertEqual(self.c.get('/api/inot/cont/').status_code, 401)

    def test_resetare_parola(self):
        self.inregistreaza()
        c = APIClient()
        r = c.post('/api/inot/auth/reset/', {'email': 'ana@test.ro'}, format='json')
        self.assertEqual(r.status_code, 200)
        r2 = c.post('/api/inot/auth/reset/', {'email': 'nimeni@test.ro'}, format='json')
        self.assertEqual(r.json(), r2.json())  # nu dezvăluie dacă emailul are cont
        self.assertEqual(len(mail.outbox), 1)
        link = [x for x in mail.outbox[0].body.split() if x.startswith('https://exemplu.test/inot/#/reset/')][0]
        uid, token = link.split('#/reset/')[1].split('/')
        r = c.post('/api/inot/auth/reset/confirma/', {'uid': uid, 'token': token, 'parola': 'Alta-parola-77x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.post('/api/inot/auth/login/', {'email': 'ana@test.ro', 'parola': 'Alta-parola-77x'},
                                format='json').status_code, 200)
        # tokenul de resetare nu mai merge a doua oară
        r = c.post('/api/inot/auth/reset/confirma/', {'uid': uid, 'token': token, 'parola': 'Iar-alta-parola-1'}, format='json')
        self.assertEqual(r.status_code, 400)


class ProgramareTest(BazaTest):
    def test_programare_din_cont(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        r = self.programeaza(d)
        self.assertEqual(r.status_code, 201, r.content)
        p = Programare.objects.get()
        self.assertEqual((p.nume_parinte, p.telefon, p.email), ('Ana Pop', '0712345678', 'ana@test.ro'))
        self.assertEqual(p.grupa, 'perfectionare')
        self.assertEqual(self.programeaza(d).status_code, 409)  # același copil, aceeași oră

    def test_locuri_epuizate(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        for i in range(7):
            self.assertEqual(self.programeaza(d, nume=f'Copil{i}').status_code, 201)
        self.assertEqual(self.programeaza(d, nume='Prea mult').status_code, 409)

    def test_lista_mea_doar_a_mea(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        self.programeaza(d)
        alt = APIClient()
        r = alt.post('/api/inot/auth/register/', {'email': 'b@test.ro', 'parola': PAROLA, 'nume': 'B', 'telefon': '0711111111'}, format='json')
        alt.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])
        self.assertEqual(alt.get('/api/inot/programarile-mele/').json(), [])
        self.assertEqual(len(self.c.get('/api/inot/programarile-mele/').json()), 1)
        pid = Programare.objects.get().id
        self.assertEqual(alt.post(f'/api/inot/programari/{pid}/anuleaza/').status_code, 404)


class AnulareTest(BazaTest):
    def test_anulare_cu_mai_mult_de_48h(self):
        self.inregistreaza()
        d = urmatoarea_data(4)
        self.programeaza(d)
        p = Programare.objects.get()
        r = self.c.post(f'/api/inot/programari/{p.id}/anuleaza/')
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.status, 'anulat')
        self.assertEqual(self.c.post(f'/api/inot/programari/{p.id}/anuleaza/').status_code, 409)

    def test_anulare_sub_48h_refuzata(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        self.programeaza(d)
        p = Programare.objects.get()
        acum = datetime.combine(d, time(17)) - timedelta(hours=47, minutes=59)
        with mock.patch('inot.services._acum_local', return_value=acum):
            self.assertFalse(self.c.get('/api/inot/programarile-mele/').json()[0]['modificabil'])
            r = self.c.post(f'/api/inot/programari/{p.id}/anuleaza/')
        self.assertEqual(r.status_code, 403)
        p.refresh_from_db()
        self.assertEqual(p.status, 'confirmat')

    def test_anulare_exact_48h_permisa(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        self.programeaza(d)
        p = Programare.objects.get()
        acum = datetime.combine(d, time(17)) - timedelta(hours=48)
        with mock.patch('inot.services._acum_local', return_value=acum):
            r = self.c.post(f'/api/inot/programari/{p.id}/anuleaza/')
        self.assertEqual(r.status_code, 200)

    def test_anularea_elibereaza_locul(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        for i in range(7):
            self.programeaza(d, nume=f'C{i}')
        p = Programare.objects.first()
        self.c.post(f'/api/inot/programari/{p.id}/anuleaza/')
        self.assertEqual(self.programeaza(d, nume='Nou').status_code, 201)

    def test_reprogramare(self):
        self.inregistreaza()
        d1, d2 = urmatoarea_data(4), urmatoarea_data(6)
        if d1.weekday() == d2.weekday():
            d2 += timedelta(days=1)
            if d2.weekday() == 6:
                d2 += timedelta(days=1)
        self.programeaza(d1)
        p = Programare.objects.get()
        r = self.c.post(f'/api/inot/programari/{p.id}/reprogrameaza/',
                        {'sablon': self.sablon_pe(d2).id, 'data': d2.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.data, d2)
        self.assertEqual(p.status, 'confirmat')
        # aceeași ședință -> refuz
        r = self.c.post(f'/api/inot/programari/{p.id}/reprogrameaza/',
                        {'sablon': self.sablon_pe(d2).id, 'data': d2.isoformat()}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_reprogramare_sub_48h_sau_ora_plina(self):
        self.inregistreaza()
        d1, d2 = urmatoarea_data(5), urmatoarea_data(6)
        self.programeaza(d1)
        p = Programare.objects.get()
        corp = {'sablon': self.sablon_pe(d2).id, 'data': d2.isoformat()}
        acum = datetime.combine(d1, time(17)) - timedelta(hours=10)
        with mock.patch('inot.services._acum_local', return_value=acum):
            self.assertEqual(self.c.post(f'/api/inot/programari/{p.id}/reprogrameaza/', corp, format='json').status_code, 403)
        # ședința țintă plină
        for i in range(7):
            Programare.objects.create(sablon=self.sablon_pe(d2), data=d2, grupa='perfectionare', nume_copil=f'x{i}',
                                      varsta=9, avansat=True, nume_parinte='p', telefon='0712345678')
        self.assertEqual(self.c.post(f'/api/inot/programari/{p.id}/reprogrameaza/', corp, format='json').status_code, 409)
        p.refresh_from_db()
        self.assertEqual(p.data, d1)


class InstructorTest(BazaTest):
    def setUp(self):
        super().setUp()
        self.inregistreaza()
        self.d = urmatoarea_data(3)
        self.programeaza(self.d)
        self.p = Programare.objects.get()
        self.instr = APIClient()
        u = User.objects.create_user('instr@test.ro', 'instr@test.ro', PAROLA, is_staff=True)
        r = self.instr.post('/api/inot/auth/login/', {'email': 'instr@test.ro', 'parola': PAROLA}, format='json')
        self.assertTrue(r.json()['cont']['instructor'])
        self.instr.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])

    def test_parintele_nu_are_acces(self):
        for url in ('/api/inot/instructor/zi/', '/api/inot/instructor/export/'):
            self.assertEqual(self.c.get(url).status_code, 403)
        self.assertEqual(self.c.patch(f'/api/inot/instructor/programari/{self.p.id}/', {'status': 'prezent'}, format='json').status_code, 403)
        self.assertEqual(APIClient().get('/api/inot/instructor/zi/').status_code, 401)

    def test_lista_pe_zi_si_prezenta(self):
        r = self.instr.get(f'/api/inot/instructor/zi/?data={self.d.isoformat()}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['programari'][0]['nume_copil'], 'Mihai')
        r = self.instr.patch(f'/api/inot/instructor/programari/{self.p.id}/', {'status': 'prezent'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'prezent')
        self.assertEqual(self.instr.patch(f'/api/inot/instructor/programari/{self.p.id}/', {'status': 'x'}, format='json').status_code, 400)

    def test_instructorul_anuleaza_fara_regula_48h(self):
        acum = datetime.combine(self.d, time(17)) - timedelta(hours=5)
        with mock.patch('inot.services._acum_local', return_value=acum):
            r = self.instr.patch(f'/api/inot/instructor/programari/{self.p.id}/', {'status': 'anulat'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_export_excel(self):
        r = self.instr.get(f'/api/inot/instructor/export/?luni={self.d.isoformat()}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])


class SuperadminTest(BazaTest):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser('boss@test.ro', 'boss@test.ro', PAROLA)
        self.boss = APIClient()
        r = self.boss.post('/api/inot/auth/login/', {'email': 'boss@test.ro', 'parola': PAROLA}, format='json')
        self.assertTrue(r.json()['cont']['superadmin'])
        self.boss.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])

    def test_doar_superadmin(self):
        self.inregistreaza()
        self.assertEqual(self.c.get('/api/inot/superadmin/instructori/').status_code, 403)
        self.assertEqual(APIClient().get('/api/inot/superadmin/instructori/').status_code, 401)
        staff = User.objects.create_user('i@test.ro', 'i@test.ro', PAROLA, is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        self.assertEqual(c.post('/api/inot/superadmin/instructori/', {'email': 'x@test.ro', 'nume': 'X'}, format='json').status_code, 403)

    def test_creeaza_instructor_si_seteaza_parola(self):
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'Nou@test.ro', 'nume': 'Nou'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(username='nou@test.ro')
        self.assertTrue(u.is_staff and not u.is_superuser and not u.has_usable_password())
        link = [x for x in mail.outbox[-1].body.split() if x.startswith('https://exemplu.test/inot/#/reset/')][0]
        uid, token = link.split('#/reset/')[1].split('/')
        r = APIClient().post('/api/inot/auth/reset/confirma/', {'uid': uid, 'token': token, 'parola': 'Instr-parola-52q'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['cont']['instructor'])
        self.assertFalse(r.json()['cont']['superadmin'])
        self.assertEqual(len(self.boss.get('/api/inot/superadmin/instructori/').json()), 1)

    def test_promoveaza_cont_existent_si_dezactiveaza(self):
        self.inregistreaza('p@test.ro')
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'p@test.ro', 'nume': 'P'}, format='json')
        self.assertEqual(r.status_code, 201)
        uid = r.json()['id']
        self.assertTrue(User.objects.get(pk=uid).has_usable_password())
        self.assertEqual(self.c.get('/api/inot/instructor/zi/').status_code, 200)
        self.boss.patch(f'/api/inot/superadmin/instructori/{uid}/', {'activ': False}, format='json')
        self.assertEqual(self.c.get('/api/inot/instructor/zi/').status_code, 401)  # tokenul a fost șters
        self.boss.patch(f'/api/inot/superadmin/instructori/{uid}/', {'activ': True}, format='json')
        self.assertEqual(self.boss.delete(f'/api/inot/superadmin/instructori/{uid}/').status_code, 204)
        self.assertFalse(User.objects.get(pk=uid).is_staff)

    def test_superadmin_vede_pagina_instructor(self):
        self.assertEqual(self.boss.get('/api/inot/instructor/zi/').status_code, 200)

    def test_nu_poate_atinge_superadmin(self):
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'boss@test.ro', 'nume': 'B'}, format='json')
        self.assertEqual(r.status_code, 400)


class LoginDinAdminTest(BazaTest):
    def test_login_cu_username_sau_email(self):
        User.objects.create_superuser('sorin', 'Sorin@Test.ro', PAROLA)
        for ident in ('sorin', 'SORIN', 'sorin@test.ro'):
            r = APIClient().post('/api/inot/auth/login/', {'email': ident, 'parola': PAROLA}, format='json')
            self.assertEqual(r.status_code, 200, ident)
            self.assertTrue(r.json()['cont']['superadmin'])
        r = APIClient().post('/api/inot/auth/login/', {'email': 'sorin', 'parola': 'gresita'}, format='json')
        self.assertEqual(r.status_code, 400)


class ProgramareStaffTest(BazaTest):
    def setUp(self):
        super().setUp()
        self.inregistreaza()  # părintele Ana Pop, cu doi copii
        d = urmatoarea_data(5)
        self.programeaza(d, nume='Mihai', varsta=8, avansat=True)
        self.programeaza(d, nume='Sara', varsta=5, avansat=False)
        self.parinte = User.objects.get(username='ana@test.ro')
        self.staff = APIClient()
        self.staff.force_authenticate(User.objects.create_user('i2@test.ro', 'i2@test.ro', PAROLA, is_staff=True))
        mail.outbox.clear()

    def test_cautare_copii(self):
        r = self.staff.get('/api/inot/instructor/copii/?q=mih').json()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]['nume_copil'], r[0]['varsta'], r[0]['avansat'], r[0]['nume_parinte'], r[0]['cont']),
                         ('Mihai', 8, True, 'Ana Pop', self.parinte.id))
        # după numele părintelui apar ambii copii, o singură dată fiecare
        self.assertEqual(len(self.staff.get('/api/inot/instructor/copii/?q=Ana').json()), 2)
        self.assertEqual(self.staff.get('/api/inot/instructor/copii/?q=m').json(), [])
        self.assertEqual(self.c.get('/api/inot/instructor/copii/?q=mih').status_code, 403)

    def test_programare_legata_de_contul_parintelui(self):
        d = urmatoarea_data(6)
        corp = {'sablon': self.sablon_pe(d).id, 'data': d.isoformat(), 'nume_copil': 'Sara', 'varsta': 5}
        self.assertEqual(self.staff.post('/api/inot/programeaza/', corp, format='json').status_code, 400)  # lipsește contul
        r = self.staff.post('/api/inot/programeaza/', {**corp, 'cont': self.parinte.id}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Programare.objects.get(data=d)
        self.assertEqual((p.user, p.nume_parinte, p.telefon, p.email), (self.parinte, 'Ana Pop', '0712345678', 'ana@test.ro'))
        self.assertEqual(len(mail.outbox), 1)  # confirmarea ajunge la părinte
        # părintele o vede (împreună cu celelalte două) și o poate anula
        self.assertEqual(len(self.c.get('/api/inot/programarile-mele/').json()), 3)

    def test_nu_se_poate_programa_pe_cont_de_staff(self):
        d = urmatoarea_data(6)
        r = self.staff.post('/api/inot/programeaza/', {
            'sablon': self.sablon_pe(d).id, 'data': d.isoformat(), 'nume_copil': 'X', 'varsta': 5,
            'cont': User.objects.get(username='i2@test.ro').id}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_parintele_nu_poate_programa_pe_alt_cont(self):
        alt = User.objects.create_user('alt@test.ro', 'alt@test.ro', PAROLA)
        Profil.objects.create(user=alt, nume='Alt Parinte', telefon='0700000000')
        d = urmatoarea_data(6)
        r = self.c.post('/api/inot/programeaza/', {
            'sablon': self.sablon_pe(d).id, 'data': d.isoformat(), 'nume_copil': 'X', 'varsta': 5, 'cont': alt.id}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Programare.objects.get(data=d).user, self.parinte)


class ParolaSiParintiTest(BazaTest):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser('boss@test.ro', 'boss@test.ro', PAROLA)
        self.boss = APIClient()
        r = self.boss.post('/api/inot/auth/login/', {'email': 'boss@test.ro', 'parola': PAROLA}, format='json')
        self.boss.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])

    def test_instructor_cu_parola_setata_direct(self):
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'i@test.ro', 'nume': 'I', 'parola': 'Parola-comuna-47'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertNotIn('#/reset/', mail.outbox[-1].body)  # fără link: are parolă
        r = APIClient().post('/api/inot/auth/login/', {'email': 'i@test.ro', 'parola': 'Parola-comuna-47'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['cont']['instructor'])
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'j@test.ro', 'nume': 'J', 'parola': '123'}, format='json')
        self.assertEqual(r.status_code, 400)  # parolă slabă

    def test_parola_nu_se_suprascrie_unui_parinte_existent(self):
        self.inregistreaza('p@test.ro')
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'p@test.ro', 'nume': 'P', 'parola': 'Alta-parola-88z'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(APIClient().post('/api/inot/auth/login/', {'email': 'p@test.ro', 'parola': PAROLA}, format='json').status_code, 200)

    def test_schimba_parola_instructor(self):
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'i@test.ro', 'nume': 'I', 'parola': 'Parola-comuna-47'}, format='json')
        uid = r.json()['id']
        r = self.boss.patch(f'/api/inot/superadmin/instructori/{uid}/', {'parola': 'Noua-parola-2026x'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['activ'])  # nu se dezactivează când schimbi doar parola
        ok = APIClient().post('/api/inot/auth/login/', {'email': 'i@test.ro', 'parola': 'Noua-parola-2026x'}, format='json')
        self.assertEqual(ok.status_code, 200)

    def test_lista_parinti_si_inactivi(self):
        self.inregistreaza('activ@test.ro')
        d = urmatoarea_data(5)
        self.programeaza(d)  # programare viitoare -> nu e inactiv
        vechi = User.objects.create_user('vechi@test.ro', 'vechi@test.ro', PAROLA)
        Profil.objects.create(user=vechi, nume='Vechi', telefon='0711111111')
        User.objects.filter(pk=vechi.pk).update(date_joined=timezone.now() - timedelta(days=200), last_login=None)
        r = self.boss.get('/api/inot/superadmin/parinti/').json()
        conturi = {c['email']: c for c in r['conturi']}
        self.assertEqual(set(conturi), {'activ@test.ro', 'vechi@test.ro'})  # fără staff/superadmin
        self.assertFalse(conturi['activ@test.ro']['inactiv'])
        self.assertEqual(conturi['activ@test.ro']['viitoare'], 1)
        self.assertTrue(conturi['vechi@test.ro']['inactiv'])
        self.assertEqual(self.c.get('/api/inot/superadmin/parinti/').status_code, 403)

    def test_stergere_cont_inactiv_si_blocare_cu_programari_viitoare(self):
        self.inregistreaza('activ@test.ro')
        d = urmatoarea_data(5)
        self.programeaza(d)
        activ = User.objects.get(username='activ@test.ro')
        r = self.boss.delete(f'/api/inot/superadmin/parinti/{activ.id}/')
        self.assertEqual(r.status_code, 400)
        Programare.objects.update(status='anulat')
        self.assertEqual(self.boss.delete(f'/api/inot/superadmin/parinti/{activ.id}/').status_code, 204)
        self.assertFalse(User.objects.filter(pk=activ.pk).exists())
        self.assertEqual(Programare.objects.count(), 1)  # istoricul rămâne, fără cont
        self.assertIsNone(Programare.objects.get().user)

    def test_nu_se_poate_sterge_staff_sau_superadmin(self):
        boss = User.objects.get(username='boss@test.ro')
        self.assertEqual(self.boss.delete(f'/api/inot/superadmin/parinti/{boss.id}/').status_code, 404)
        self.assertTrue(User.objects.filter(pk=boss.pk).exists())
