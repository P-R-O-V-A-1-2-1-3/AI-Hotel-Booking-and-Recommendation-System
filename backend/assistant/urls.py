from django.urls import path

from .streaming import ChatStreamView
from .views import ChatView, PicksView

urlpatterns = [
    path('chat/', ChatView.as_view(), name='ai-chat'),
    path('chat/stream/', ChatStreamView.as_view(), name='ai-chat-stream'),
    path('picks/', PicksView.as_view(), name='ai-picks'),
]
