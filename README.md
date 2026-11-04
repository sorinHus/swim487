# SWIM487 — swimming lesson bookings

Django server (REST API + admin) behind the public page at `487.ro/inot`. The front end is a single static page (`index.html` + `inot.css` + `inot.js`, vanilla JS, hash routing) living in the `portfolio` repo and served from Cloudflare Pages.

## Roles

- **Visitors** — can browse the weekly calendar and see the free places per level for each session. Booking requires an account.
- **Parents** — sign up with email and password (password reset by email). They book a child into a session, then see their bookings under *My bookings*, where they can cancel or reschedule up to **48 hours** before the session (`Setari.ore_anulare`). Inside that window the buttons are disabled and the reason is shown.
- **Instructors** (`is_staff`) — the *Sessions* page: bookings per day, **Present / Absent** marking, cancel and reschedule (same 48 h rule, parents are notified by email), and booking on behalf of a parent (search the child; the booking is linked to the parent's account). Weekly **Excel export** in the layout of the existing worksheet (`programari_inot.xlsx`).
- **Superadmin** (Django superuser) — creates, deactivates and removes instructor accounts (optionally with a password set directly, otherwise the instructor gets an email link to choose one), and has a separate *Parents* page: all parent accounts, flagged when inactive (no upcoming bookings and no activity for 90 days), with password reset (email link or set directly), email change (only the superadmin can change an account email), deactivate and delete. Django's `/admin/` remains available for the timetable, closed days and settings.

Rules: children under 7, or beginners, go to the *initiere* group; 7+ and advanced go to *perfecționare*. 7 places per group per session (configurable).

## API overview

All routes live under `/api/inot/` (see `inot/urls.py`):

| Area | Routes |
| --- | --- |
| Public | `disponibil/` (availability) |
| Accounts | `auth/register/`, `auth/login/` (email or username), `auth/logout/`, `auth/reset/`, `auth/reset/confirma/`, `cont/` |
| Parents | `programeaza/`, `programarile-mele/`, `programari/<id>/anuleaza/`, `programari/<id>/reprogrameaza/` |
| Instructors | `instructor/zi/`, `instructor/programari/<id>/` (present/absent), `…/anuleaza/`, `…/reprogrameaza/`, `instructor/copii/` (child search), `instructor/export/` |
| Superadmin | `superadmin/instructori/…`, `superadmin/parinti/…` |

Authentication uses DRF tokens that expire after 30 days. Login, registration and password reset are rate limited. Bookings are made inside a transaction that locks the settings row, so two simultaneous requests cannot exceed a group's places.

## Local development

```
python -m venv venv && venv\Scripts\pip install -r requirements.txt
set DEBUG=True
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py seteaza_orar      # Mon–Fri 17:00/18:00, Sat 10:00/11:00
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python manage.py runserver
```

For the front end, run `window.INOT_API='http://127.0.0.1:8000'` in the browser console before the page loads, or edit the `API` constant in `inot.js`.

Tests (41): `python manage.py test inot`

## Deploy (Railway)

Environment variables (see `.env.example`): `SECRET_KEY`, `DATABASE_URL` (from the Postgres plugin), `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS=https://487.ro`, `CSRF_TRUSTED_ORIGINS`, `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`, `EMAIL_ADMIN`, and `FRONTEND_URL` (used for the links in password-reset emails).

The `Procfile` runs `collectstatic` and `migrate` on every deploy. After the first deploy run `python manage.py seteaza_orar` and `createsuperuser` from the Railway console.
