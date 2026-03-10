from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

def get_admin_navigation(request):
    """
    Returns completely separate sidebar navigation depending on whether
    the user is superuser or not.
    """
    if request.user.is_superuser:
        # ────────────────────────────────────────────────
        # Superuser / Developer menu
        # ────────────────────────────────────────────────
        return [
            {
                "title": _("Dashboard"),
                "items": [
                    {
                        "title": _("Overview"),
                        "link": reverse_lazy("admin:index"),  # or your custom dashboard if you have one
                        "icon": "dashboard",
                    }
                ]
            },
            {
                "title": _("Account info & Management"),
                "collapsible": True,
                "items": [

                    {
                        "title": _("All Users"),
                        "link": reverse_lazy("admin:accounts_user_changelist"),
                        "icon": "people",
                    },
                    {
                        "title": _("Regular accounts"),
                        "link": reverse_lazy("admin:accounts_customerproxy_changelist"),
                        "icon": "account_circle",
                    },
                    {
                        "title": _("Vendor accounts"),
                        "link": reverse_lazy("admin:accounts_vendorproxy_changelist"),
                        "icon": "productivity",
                    },
                    {
                      "title": _("Staff accounts"),
                      "link": reverse_lazy("admin:accounts_staffproxy_changelist"),
                      "icon": "supervisor_account",
                    },

                    {
                        "title": _("All Stores"),
                        "link": reverse_lazy("admin:accounts_laundrymartstore_changelist"),
                        "icon": "storefront",
                    },
                    # Add more system-level views here when needed
                    # e.g. groups, permissions, sessions, logs, etc.
                ]
            },
          {
            "title": _("Orders"),
            "items": [
              {
                "title": _("Quote Requests"),
                "link": reverse_lazy("admin:uber_deliveryquote_changelist"),
                "icon": "request_quote",
              },
              {
                "title": _("Converted Orders"),
                "link": reverse_lazy("admin:payment_order_changelist"),
                "icon": "order_approve",
              }
            ]
          },
            {
                "title": _("Communication"),

                "items": [
                    {
                        "title": _("Chat with Customers"),
                        "link": reverse_lazy("admin:messaging_room_changelist"),
                        "icon": "chat",
                    }
                ]
            },
            # You can add more superuser-only sections later
          {
            "title": _("Global settings"),
            "collapsible": True,
            "items": [
              {
                "title": _("Fee, and bag settings"),
                "link": reverse_lazy("admin:admin_panel_globalmanifest_changelist"),
                "icon": "admin_meds",
              },
              {
                "title": _("Notifications Texts"),
                "link": reverse_lazy("admin:admin_panel_notificationtext_changelist"),
                "icon": "edit_notifications",
              },
              {
                "title": _("Slider images"),
                "link": reverse_lazy("admin:admin_panel_slideimage_changelist"),
                "icon": "edit_notifications",
              }
            ]
          },
        ]

    else:
        # ────────────────────────────────────────────────
        # Normal staff / laundrymart vendor menu
        # (assumes is_staff or in group 'laundrymart_staff' — but you can adjust)
        # ────────────────────────────────────────────────
        if not (request.user.is_staff or request.user.groups.filter(name="laundrymart_staff").exists()):
            return []  # or raise error / redirect — depending on your security needs

        return [
          {
            "title": _("Dashboard"),
            "items": [
              {
                "title": _("Overview"),
                "link": reverse_lazy("admin:vendor_vendordashboard_changelist"),
                "icon": "dashboard",
              }
            ]
          },
            {
                "title": _("Store & Profile"),
                "separator": True,
                "items": [
                    {
                        "title": _("My Stores"),
                        "link": reverse_lazy("admin:accounts_laundrymartstore_changelist"),
                        "icon": "store",
                    }
                ]
            },
            {
                "title": _("Team"),
                "items": [
                    {
                        "title": _("Employees"),
                        "link": reverse_lazy("admin:accounts_employee_changelist"),
                        "icon": "group",
                    },

                ]
            },
            {
                "title": _("Orders"),
                "items": [
                    {
                        "title": _("Quote Requests"),
                        "link": reverse_lazy("admin:uber_deliveryquote_changelist"),
                        "icon": "request_quote",
                    },
                    {
                        "title": _("Converted Orders"),
                        "link": reverse_lazy("admin:payment_order_changelist"),
                        "icon": "order_approve",
                    }
                ]
            },
            {
                "title": _("Finances"),
                "items": [
                    {
                        "title": _("Earnings"),
                        "icon": "payments",  # ← remember to add real link later
                        # "link": reverse_lazy("admin:your_earnings_view"),
                    },
                    {
                        "title": _("Payment Methods"),
                        "link": reverse_lazy("admin:vendor_payment_methods"),
                        "icon": "credit_card",
                    }
                ]
            },
            {
              "title": _("Reports"),
              "items": [
                {
                  "title": _("Sales Summary"),
                  "link": reverse_lazy("admin:vendor_sales_summary"),
                  "icon": "bar_chart",
                }
              ]
            },
            {
                "title": _("Communication"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Chat with Customers"),
                        "link": reverse_lazy("admin:messaging_room_changelist"),
                        "icon": "chat",
                    }
                ]
            },
          {
            "title": _("Support"),
            "collapsible": True,
            "items": [
              {
                "title": _("Customer Reports"),
                "link": reverse_lazy("admin:customer_orderreport_changelist"),
                "icon": "report_problem",
              }
            ]
          },


        ]