from django.urls import path

from payment.views import VendorOnboardingCompleteView, VendorOnboardingRefreshView, VendorOnboardingView, \
  add_card_backend, delete_saved_card, \
  retrieve_saved_cards, \
  stripe_cancel, stripe_success

urlpatterns = [
  path("success/", stripe_success, name="stripe_success"),
  path("cancel/", stripe_cancel, name="stripe_cancel"),
  path("add-card/", add_card_backend, name="stripe_embedded_add_card"),
  path('retrieve-cards/', retrieve_saved_cards, name='stripe_retrieve_cards'),
  path('delete-card/<str:payment_method_id>', delete_saved_card, name='delete_saved_card'),
]
