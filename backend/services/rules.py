"""Versioned safety policy shared by simulation and the PostgreSQL catalog.

This is a fixed local protection: it continues to work if brokers or API fail.
Database records document this policy; they are not an editable remote override.
"""

THERMAL_PROTECTION = {
    "activate_at_c": 65.0,
    "release_at_c": 55.0,
    "limited_power_percent": 30.0,
}
