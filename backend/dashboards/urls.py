from django.urls import path

from . import properties, views

urlpatterns = [
    path('dashboard/me/', views.MyDashboardView.as_view(), name='dashboard-me'),

    # Hotel owners
    path('owner/overview/', views.OwnerOverviewView.as_view(), name='owner-overview'),
    path('owner/hotels/', properties.OwnerHotelListView.as_view(), name='owner-hotels'),
    path('owner/hotels/<int:pk>/', properties.OwnerHotelDetailView.as_view(), name='owner-hotel'),
    path('owner/hotels/<int:pk>/submit/', properties.OwnerHotelSubmitView.as_view(), name='owner-hotel-submit'),
    path('owner/hotels/<int:pk>/photos/', properties.OwnerHotelPhotosView.as_view(), name='owner-hotel-photos'),
    path('owner/hotels/<int:pk>/rooms/', properties.OwnerHotelRoomsView.as_view(), name='owner-hotel-rooms'),
    path('owner/photos/<int:pk>/', properties.OwnerPhotoView.as_view(), name='owner-photo'),
    path('owner/rooms/<int:pk>/', properties.OwnerRoomView.as_view(), name='owner-room'),
    path('owner/claims/', properties.OwnerClaimsView.as_view(), name='owner-claims'),
    path('owner/claimable/', properties.ClaimableHotelsView.as_view(), name='owner-claimable'),

    # Platform admin
    path('admin/overview/', views.AdminOverviewView.as_view(), name='admin-overview'),
    path('admin/hotels/<int:pk>/decision/', views.AdminHotelDecisionView.as_view(), name='admin-hotel-decision'),
    path('admin/claims/<int:pk>/decision/', views.AdminClaimDecisionView.as_view(), name='admin-claim-decision'),
    path('admin/reviews/<int:pk>/', views.AdminReviewView.as_view(), name='admin-review'),
    path('admin/users/<int:pk>/status/', views.AdminUserStatusView.as_view(), name='admin-user-status'),
]
