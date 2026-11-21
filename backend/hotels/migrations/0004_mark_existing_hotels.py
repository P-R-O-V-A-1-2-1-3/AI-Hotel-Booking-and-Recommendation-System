from django.db import migrations


def mark_existing(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    # Everything created before owner listings existed came from the demo seed
    Hotel.objects.all().update(source='demo')
    # Hidden hotels were the "pending approval" queue in the old model
    Hotel.objects.filter(is_active=False).update(approval_status='pending')


class Migration(migrations.Migration):
    dependencies = [
        ('hotels', '0003_hotel_approval_status_hotel_external_id_hotel_phone_and_more'),
    ]

    operations = [
        migrations.RunPython(mark_existing, migrations.RunPython.noop),
    ]
