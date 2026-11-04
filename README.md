# SWIM487 — programări la înot

Server Django (API + pagina de admin) pentru pagina publică `487.ro/inot`.

- **Părinții**: `portfolio/inot/index.html` apelează `/api/inot/disponibil/` și `/api/inot/programeaza/`.
- **Admin**: `/admin/` — programări (filtre, anulare, export Excel pe săptămână), orar săptămânal, zile închise, setări (locuri, câte săptămâni în avans, text pentru email).
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
Variabile: vezi `.env.example` (`SECRET_KEY`, `DATABASE_URL` din pluginul Postgres, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS=https://487.ro`, `CSRF_TRUSTED_ORIGINS`, `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`, `EMAIL_ADMIN`).
După primul deploy: `python manage.py seteaza_orar` și `createsuperuser` din consola Railway.
