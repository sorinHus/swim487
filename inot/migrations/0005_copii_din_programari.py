from django.db import migrations


def creeaza_copii(apps, schema_editor):
    """Programările existente ale conturilor de părinți devin copii salvați pe cont (câte unul per nume)."""
    Programare = apps.get_model('inot', 'Programare')
    Copil = apps.get_model('inot', 'Copil')
    copii = {}
    for p in Programare.objects.filter(user__isnull=False, copil__isnull=True).order_by('creat_la'):
        cheie = (p.user_id, p.nume_copil.strip().lower())
        c = copii.get(cheie)
        if c is None:
            c = copii[cheie] = Copil.objects.create(
                user_id=p.user_id, nume=p.nume_copil.strip(), varsta=p.varsta, avansat=p.avansat)
        else:  # cea mai recentă programare dă vârsta și nivelul curente
            c.varsta, c.avansat = p.varsta, p.avansat
            c.save(update_fields=['varsta', 'avansat'])
        p.copil_id = c.id
        p.save(update_fields=['copil'])


class Migration(migrations.Migration):
    dependencies = [('inot', '0004_copii')]
    operations = [migrations.RunPython(creeaza_copii, migrations.RunPython.noop)]
