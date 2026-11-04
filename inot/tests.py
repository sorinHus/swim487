from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Copil, Profil, Programare, Sablon, Setari

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

    def test_prezent_si_absent(self):
        url = f'/api/inot/instructor/programari/{self.p.id}/'
        self.assertEqual(self.instr.patch(url, {'status': 'absent'}, format='json').json()['status'], 'absent')
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'absent')
        self.assertEqual(self.instr.patch(url, {'status': 'confirmat'}, format='json').status_code, 200)  # corectare
        # anularea nu mai trece pe această rută
        self.assertEqual(self.instr.patch(url, {'status': 'anulat'}, format='json').status_code, 400)

    def test_instructorul_anuleaza_cu_regula_48h(self):
        url = f'/api/inot/instructor/programari/{self.p.id}/anuleaza/'
        sub = datetime.combine(self.d, time(17)) - timedelta(hours=47)
        with mock.patch('inot.services._acum_local', return_value=sub):
            zi = self.instr.get(f'/api/inot/instructor/zi/?data={self.d.isoformat()}').json()['programari'][0]
            self.assertFalse(zi['modificabil'])
            self.assertEqual(zi['ore_anulare'], 48)
            self.assertEqual(self.instr.post(url).status_code, 403)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'confirmat')
        peste = datetime.combine(self.d, time(17)) - timedelta(hours=49)
        with mock.patch('inot.services._acum_local', return_value=peste):
            self.assertEqual(self.instr.post(url).status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'anulat')
        self.assertEqual(mail.outbox[-1].to, ['ana@test.ro'])  # părintele e anunțat

    def test_instructorul_reprogrameaza_cu_regula_48h(self):
        d2 = urmatoarea_data(5)
        if d2.weekday() == self.d.weekday():
            d2 += timedelta(days=1)
            if d2.weekday() == 6:
                d2 += timedelta(days=1)
        corp = {'sablon': self.sablon_pe(d2).id, 'data': d2.isoformat()}
        url = f'/api/inot/instructor/programari/{self.p.id}/reprogrameaza/'
        sub = datetime.combine(self.d, time(17)) - timedelta(hours=10)
        with mock.patch('inot.services._acum_local', return_value=sub):
            self.assertEqual(self.instr.post(url, corp, format='json').status_code, 403)
        r = self.instr.post(url, corp, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.p.refresh_from_db()
        self.assertEqual(self.p.data, d2)
        # părintele nu poate folosi rutele de instructor
        self.assertEqual(self.c.post(url, corp, format='json').status_code, 403)

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
        mihai = Copil.objects.get(nume='Mihai')
        self.assertEqual((r[0]['nume_copil'], r[0]['varsta'], r[0]['avansat'], r[0]['nume_parinte'], r[0]['copil']),
                         ('Mihai', 8, True, 'Ana Pop', mihai.id))
        # după numele părintelui apar ambii copii, o singură dată fiecare
        self.assertEqual(len(self.staff.get('/api/inot/instructor/copii/?q=Ana').json()), 2)
        self.assertEqual(self.staff.get('/api/inot/instructor/copii/?q=m').json(), [])
        self.assertEqual(self.c.get('/api/inot/instructor/copii/?q=mih').status_code, 403)

    def test_programare_legata_de_contul_parintelui(self):
        d = urmatoarea_data(6)
        sara = Copil.objects.get(nume='Sara')
        corp = {'sablon': self.sablon_pe(d).id, 'data': d.isoformat()}
        self.assertEqual(self.staff.post('/api/inot/programeaza/', corp, format='json').status_code, 400)  # lipsește copilul
        r = self.staff.post('/api/inot/programeaza/', {**corp, 'copil': sara.id}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Programare.objects.get(data=d)
        self.assertEqual((p.user, p.copil, p.nume_copil, p.nume_parinte, p.telefon, p.email),
                         (self.parinte, sara, 'Sara', 'Ana Pop', '0712345678', 'ana@test.ro'))
        self.assertEqual(len(mail.outbox), 1)  # confirmarea ajunge la părinte
        # părintele o vede (împreună cu celelalte două) și o poate anula
        self.assertEqual(len(self.c.get('/api/inot/programarile-mele/').json()), 3)

    def test_staff_nu_poate_programa_copil_inexistent_sau_de_staff(self):
        d = urmatoarea_data(6)
        corp = {'sablon': self.sablon_pe(d).id, 'data': d.isoformat()}
        self.assertEqual(self.staff.post('/api/inot/programeaza/', {**corp, 'copil': 99999}, format='json').status_code, 400)
        self.assertEqual(self.staff.post('/api/inot/programeaza/', {**corp, 'nume_copil': 'X', 'varsta': 5},
                                         format='json').status_code, 400)  # staff nu creează copii

    def test_parintele_nu_poate_programa_copilul_altui_parinte(self):
        alt = User.objects.create_user('alt@test.ro', 'alt@test.ro', PAROLA)
        Profil.objects.create(user=alt, nume='Alt Parinte', telefon='0700000000')
        strain = Copil.objects.create(user=alt, nume='Strain', varsta=6, avansat=False)
        d = urmatoarea_data(6)
        r = self.c.post('/api/inot/programeaza/', {
            'sablon': self.sablon_pe(d).id, 'data': d.isoformat(), 'copil': strain.id}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Programare.objects.filter(data=d).exists())


class CopiiTest(BazaTest):
    def setUp(self):
        super().setUp()
        self.inregistreaza()
        self.parinte = User.objects.get(username='ana@test.ro')

    def test_prima_programare_salveaza_copilul(self):
        d = urmatoarea_data(5)
        self.assertEqual(self.c.get('/api/inot/copii/').json(), [])
        self.assertEqual(self.programeaza(d, nume='Mihai', varsta=8, avansat=True).status_code, 201)
        copii = self.c.get('/api/inot/copii/').json()
        self.assertEqual([(c['nume'], c['varsta'], c['avansat'], c['grupa'], c['viitoare']) for c in copii],
                         [('Mihai', 8, True, 'perfectionare', 1)])
        # a doua programare: copilul se alege din listă, fără a mai retrimite datele
        d2 = urmatoarea_data(6)
        r = self.c.post('/api/inot/programeaza/', {
            'sablon': self.sablon_pe(d2).id, 'data': d2.isoformat(), 'copil': copii[0]['id']}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Programare.objects.get(data=d2)
        self.assertEqual((p.nume_copil, p.varsta, p.avansat, p.grupa), ('Mihai', 8, True, 'perfectionare'))
        self.assertEqual(Copil.objects.count(), 1)

    def test_acelasi_nume_reintrodus_nu_dubleaza_copilul(self):
        d = urmatoarea_data(5)
        self.programeaza(d, nume='Mihai', varsta=8, avansat=False)
        d2 = urmatoarea_data(6)
        self.programeaza(d2, nume='mihai', varsta=9, avansat=True)  # a crescut și a învățat să înoate
        self.assertEqual(Copil.objects.count(), 1)
        c = Copil.objects.get()
        self.assertEqual((c.varsta, c.avansat), (9, True))

    def test_adauga_editeaza_sterge(self):
        r = self.c.post('/api/inot/copii/', {'nume': 'Sara', 'varsta': 5, 'avansat': False}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()['id']
        self.assertEqual(self.c.post('/api/inot/copii/', {'nume': 'SARA', 'varsta': 6}, format='json').status_code, 400)  # nume duplicat
        self.assertEqual(self.c.post('/api/inot/copii/', {'nume': 'X', 'varsta': 2}, format='json').status_code, 400)  # vârstă invalidă
        r = self.c.patch(f'/api/inot/copii/{cid}/', {'varsta': 6, 'avansat': True}, format='json')
        self.assertEqual((r.json()['varsta'], r.json()['avansat'], r.json()['nume']), (6, True, 'Sara'))
        self.assertEqual(self.c.delete(f'/api/inot/copii/{cid}/').status_code, 204)
        self.assertEqual(self.c.get('/api/inot/copii/').json(), [])

    def test_copiii_sunt_privati(self):
        self.c.post('/api/inot/copii/', {'nume': 'Sara', 'varsta': 5}, format='json')
        cid = Copil.objects.get().id
        alt = APIClient()
        r = alt.post('/api/inot/auth/register/', {'email': 'b@test.ro', 'parola': PAROLA, 'nume': 'B', 'telefon': '0711111111'}, format='json')
        alt.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])
        self.assertEqual(alt.get('/api/inot/copii/').json(), [])
        self.assertEqual(alt.patch(f'/api/inot/copii/{cid}/', {'nume': 'Furat'}, format='json').status_code, 404)
        self.assertEqual(alt.delete(f'/api/inot/copii/{cid}/').status_code, 404)
        self.assertEqual(APIClient().get('/api/inot/copii/').status_code, 401)

    def test_redenumirea_actualizeaza_programarile_viitoare_dar_nu_si_nivelul(self):
        d = urmatoarea_data(5)
        self.programeaza(d, nume='Mihai', varsta=6, avansat=False)
        cid = Copil.objects.get().id
        r = self.c.patch(f'/api/inot/copii/{cid}/', {'nume': 'Mihnea', 'varsta': 8, 'avansat': True}, format='json')
        self.assertEqual(r.status_code, 200)
        p = Programare.objects.get()
        self.assertEqual((p.nume_copil, p.grupa, p.varsta), ('Mihnea', 'initiere', 6))  # grupa programării rămâne

    def test_stergere_blocata_cu_programari_viitoare(self):
        d = urmatoarea_data(5)
        self.programeaza(d, nume='Mihai', varsta=8)
        cid = Copil.objects.get().id
        self.assertEqual(self.c.delete(f'/api/inot/copii/{cid}/').status_code, 400)
        Programare.objects.update(status='anulat')
        self.assertEqual(self.c.delete(f'/api/inot/copii/{cid}/').status_code, 204)
        self.assertEqual(Programare.objects.count(), 1)  # istoricul rămâne
        self.assertIsNone(Programare.objects.get().copil)


class ContulMeuTest(BazaTest):
    def test_editare_date_personale_actualizeaza_programarile_viitoare(self):
        self.inregistreaza()
        d = urmatoarea_data(5)
        self.programeaza(d)
        r = self.c.patch('/api/inot/cont/', {'nume': 'Ana Maria Pop', 'telefon': '0799888777'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['nume'], r.json()['telefon']), ('Ana Maria Pop', '0799888777'))
        p = Programare.objects.get()
        self.assertEqual((p.nume_parinte, p.telefon), ('Ana Maria Pop', '0799888777'))
        self.assertEqual(self.c.patch('/api/inot/cont/', {'nume': 'X', 'telefon': 'abc'}, format='json').status_code, 400)

    def test_schimbare_parola(self):
        self.inregistreaza()
        r = self.c.post('/api/inot/cont/parola/', {'parola_veche': 'gresita', 'parola_noua': 'Noua-parola-2026x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.c.post('/api/inot/cont/parola/', {'parola_veche': PAROLA, 'parola_noua': '123'}, format='json')
        self.assertEqual(r.status_code, 400)  # prea slabă
        r = self.c.post('/api/inot/cont/parola/', {'parola_veche': PAROLA, 'parola_noua': 'Noua-parola-2026x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        nou = r.json()['token']  # sesiunea curentă rămâne valabilă prin token nou
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION='Token ' + nou)
        self.assertEqual(c2.get('/api/inot/cont/').status_code, 200)
        self.assertEqual(self.c.get('/api/inot/cont/').status_code, 401)  # tokenul vechi s-a închis
        ok = APIClient().post('/api/inot/auth/login/', {'email': 'ana@test.ro', 'parola': 'Noua-parola-2026x'}, format='json')
        self.assertEqual(ok.status_code, 200)


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


class ExportFormatTest(BazaTest):
    def test_format_foaie_de_lucru(self):
        from io import BytesIO
        from openpyxl import load_workbook
        for z in range(6):  # a doua oră a zilei, ca în foaia originală (17:00 și 18:00)
            Sablon.objects.create(zi=z, ora_start=time(18), ora_sfarsit=time(19))
        staff = User.objects.create_user('ex@test.ro', 'ex@test.ro', PAROLA, is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        luni = urmatoarea_data(7)
        luni -= timedelta(days=luni.weekday())
        marti = luni + timedelta(days=1)
        s17 = Sablon.objects.get(zi=1, ora_start=time(17))
        s18 = Sablon.objects.get(zi=1, ora_start=time(18))
        for i, (sab, grupa, nume) in enumerate([(s17, 'initiere', 'Mihai'), (s17, 'initiere', 'Sara'),
                                                (s17, 'perfectionare', 'Dan'), (s18, 'initiere', 'Ioana')]):
            Programare.objects.create(sablon=sab, data=marti, grupa=grupa, nume_copil=nume, varsta=6,
                                      nume_parinte='P', telefon='0712345678')
        Programare.objects.create(sablon=s17, data=marti, grupa='initiere', nume_copil='Anulat', varsta=6,
                                  nume_parinte='P', telefon='0712345678', status='anulat')
        r = c.get(f'/api/inot/instructor/export/?luni={luni.isoformat()}')
        ws = load_workbook(BytesIO(r.content)).active
        # Luni în coloanele A–D, marți în G–J (două coloane libere între zile), ca în programari_inot.xlsx
        self.assertEqual((ws['C5'].value, ws['D5'].value, ws['I5'].value), ('Nume', 'Nume', 'Nume'))
        self.assertEqual((ws['C6'].value, ws['D6'].value), (time(17), time(18)))
        self.assertEqual((ws['I6'].value, ws['J6'].value), (time(17), time(18)))
        self.assertEqual(ws['B7'].value, 'Nivel: inițiere / 3-6 ani')
        self.assertEqual(ws['B14'].value, 'Nivel: perf / 7+ ani')
        self.assertEqual([ws.cell(r_, 1).value for r_ in (7, 13, 14, 20)], [1, 7, 8, 14])
        self.assertEqual((ws['I7'].value, ws['I8'].value, ws['I9'].value), ('Mihai', 'Sara', None))  # fără cea anulată
        self.assertEqual(ws['I14'].value, 'Dan')
        self.assertEqual(ws['J7'].value, 'Ioana')
        self.assertEqual(ws['A23'].value, None)
        self.assertEqual(ws['A24'].value.date(), luni + timedelta(days=2))  # al doilea bloc: miercuri + joi


class ResetareParintiTest(BazaTest):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser('boss@test.ro', 'boss@test.ro', PAROLA)
        self.boss = APIClient()
        r = self.boss.post('/api/inot/auth/login/', {'email': 'boss@test.ro', 'parola': PAROLA}, format='json')
        self.boss.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])
        self.inregistreaza('p@test.ro')
        self.p = User.objects.get(username='p@test.ro')
        mail.outbox.clear()

    def test_seteaza_parola_noua(self):
        r = self.boss.patch(f'/api/inot/superadmin/parinti/{self.p.id}/', {'parola': 'Parola-noua-3391'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['activ'])
        self.assertEqual(self.c.get('/api/inot/cont/').status_code, 401)  # sesiunea veche s-a închis
        ok = APIClient().post('/api/inot/auth/login/', {'email': 'p@test.ro', 'parola': 'Parola-noua-3391'}, format='json')
        self.assertEqual(ok.status_code, 200)
        r = self.boss.patch(f'/api/inot/superadmin/parinti/{self.p.id}/', {'parola': '123'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_trimite_link_resetare(self):
        r = self.boss.post(f'/api/inot/superadmin/parinti/{self.p.id}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(mail.outbox[0].to, ['p@test.ro'])
        self.assertIn('#/reset/', mail.outbox[0].body)
        self.assertEqual(self.c.post(f'/api/inot/superadmin/parinti/{self.p.id}/').status_code, 403)


class SchimbaEmailTest(BazaTest):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser('boss@test.ro', 'boss@test.ro', PAROLA)
        self.boss = APIClient()
        r = self.boss.post('/api/inot/auth/login/', {'email': 'boss@test.ro', 'parola': PAROLA}, format='json')
        self.boss.credentials(HTTP_AUTHORIZATION='Token ' + r.json()['token'])
        self.inregistreaza('vechi@test.ro')
        self.p = User.objects.get(username='vechi@test.ro')

    def test_superadmin_schimba_emailul_parintelui(self):
        r = self.boss.patch(f'/api/inot/superadmin/parinti/{self.p.id}/', {'email': 'Nou@Test.ro'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['email'], 'nou@test.ro')
        self.p.refresh_from_db()
        self.assertEqual((self.p.username, self.p.email), ('nou@test.ro', 'nou@test.ro'))
        ok = APIClient().post('/api/inot/auth/login/', {'email': 'nou@test.ro', 'parola': PAROLA}, format='json')
        self.assertEqual(ok.status_code, 200)
        vechi = APIClient().post('/api/inot/auth/login/', {'email': 'vechi@test.ro', 'parola': PAROLA}, format='json')
        self.assertEqual(vechi.status_code, 400)

    def test_email_invalid_sau_deja_folosit(self):
        for corp in ({'email': 'nu-e-email'}, {'email': 'boss@test.ro'}):
            r = self.boss.patch(f'/api/inot/superadmin/parinti/{self.p.id}/', corp, format='json')
            self.assertEqual(r.status_code, 400, corp)
        self.p.refresh_from_db()
        self.assertEqual(self.p.email, 'vechi@test.ro')

    def test_instructor_si_drepturi(self):
        r = self.boss.post('/api/inot/superadmin/instructori/', {'email': 'i@test.ro', 'nume': 'I', 'parola': 'Parola-comuna-47'}, format='json')
        iid = r.json()['id']
        r = self.boss.patch(f'/api/inot/superadmin/instructori/{iid}/', {'email': 'instr@test.ro'}, format='json')
        self.assertEqual((r.status_code, r.json()['email']), (200, 'instr@test.ro'))
        # părintele nu își poate schimba emailul (nici prin cont/)
        r = self.c.patch('/api/inot/cont/', {'nume': 'Ana', 'telefon': '0712345678', 'email': 'furat@test.ro'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.email, 'vechi@test.ro')
        self.assertEqual(self.c.patch(f'/api/inot/superadmin/parinti/{self.p.id}/', {'email': 'x@test.ro'}, format='json').status_code, 403)
