"""Platform tenant lifecycle routes (T025–T051, T043–T044).

All routes require the platform super-admin (``__platform__``) via
``get_current_platform_admin``. The business routes are guarded in the
opposite direction by ``get_current_admin_user`` (T022).
"""
