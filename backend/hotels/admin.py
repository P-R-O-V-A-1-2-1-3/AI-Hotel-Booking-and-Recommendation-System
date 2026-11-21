from django.contrib import admin

from .models import Hotel, Review, Room, WishlistItem


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'price_per_night', 'rating', 'match_score', 'featured', 'is_active']
    list_filter = ['city', 'featured', 'is_active']
    list_editable = ['featured', 'is_active']
    search_fields = ['name', 'city', 'location']
    inlines = [RoomInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['author_name', 'hotel', 'rating', 'traveler_type', 'is_flagged', 'created_at']
    list_filter = ['is_flagged', 'traveler_type', 'rating']
    list_editable = ['is_flagged']
    search_fields = ['author_name', 'title', 'comment', 'hotel__name']


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ['user', 'hotel', 'created_at']
