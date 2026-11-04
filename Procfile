web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn backend.wsgi --bind 0.0.0.0:$PORT
