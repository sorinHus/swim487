# SWIM487 — programări la înot

Server Django (API + pagina de admin) pentru pagina publică `487.ro/inot`.

- **Părinți**: cont cu email și parolă (resetare prin email); calendarul e public, programarea cere cont. Văd programările, le anulează sau reprogramează cu minimum 48h înainte (`Setari.ore_anulare`).
- **Instructori** (`is_staff`): pagina „Ședințe" din `487.ro/inot` — lista pe zi, prezență, anulare, export Excel pe săptămână, programare la cererea părinților (caută copilul, programarea se leagă de contul părintelui).
- **Superadmin**: creează/dezactivează conturi de instructori din aceeași pagină (instructorul își setează parola printr-un link pe email). `/admin/` rămâne pentru orar, zile închise și setări.
- **API**: `inot/urls.py`; autentificare cu token DRF (expiră în 30 de zile), rate limit pe login/înregistrare/resetare; 30 de teste (`python manage.py test inot`).
- **Reguli**: sub 7 ani sau începător → inițiere; 7+ ani și avansat → perfecționare. 7 locuri pe grupă (configurabil).

## Pornire locală
```
python -m venv venv && venv\Scripts\pip install -r requirements.txt
set DEBUG=True
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py seteaza_orar      # luni–vineri 17:00/18:00, sâmbătă 10:00/11:00
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python manage.py runserver
```
Pentru pagina locală: în consola browserului `window.INOT_API='http://127.0.0.1:8000'` înainte de încărcare, sau editează constanta `API`.

## Deploy (Railway)
Variabile: vezi `.env.example` (`SECRET_KEY`, `DATABASE_URL` din pluginul Postgres, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS=https://487.ro`, `CSRF_TRUSTED_ORIGINS`, `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`, `EMAIL_ADMIN`, `FRONTEND_URL` pentru linkurile de resetare parolă).
După primul deploy: `python manage.py seteaza_orar` și `createsuperuser` din consola Railway.
