from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_ref', 'hotel', 'room', 'guest_name', 'check_in', 'check_out', 'total_price',
                    'payment_method', 'status']
    list_filter = ['status', 'payment_method', 'hotel']
    search_fields = ['booking_ref', 'guest_name', 'guest_email', 'guest_phone']
    readonly_fields = ['booking_ref', 'room_total', 'tax', 'addons_total', 'discount', 'total_price',
                       'created_at', 'updated_at']
    date_hierarchy = 'check_in'
