"""Settings store module reading and writing dynamic runtime settings against app_settings table."""

from typing import Optional

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AppSetting
from app.db.session import SessionLocal
from app.schemas.admin import AdminSettingsResponse, AdminSettingsUpdate

SETTING_ACTIVE_MODEL = "active_model"
SETTING_FALLBACK_MODEL = "fallback_model"


def get_admin_settings(
    db: Optional[Session] = None,
    settings: Optional[Settings] = None,
) -> AdminSettingsResponse:
    """Read active and fallback model settings on every request without caching.

    Falls back to configured application settings if absent in app_settings table.
    """
    app_settings = settings or get_settings()
    active = app_settings.active_model
    fallback = app_settings.fallback_model

    if db is not None:
        try:
            active_row = db.get(AppSetting, SETTING_ACTIVE_MODEL)
            if (
                active_row
                and hasattr(active_row, "value")
                and isinstance(active_row.value, str)
                and active_row.value.strip()
            ):
                active = active_row.value.strip()

            fallback_row = db.get(AppSetting, SETTING_FALLBACK_MODEL)
            if (
                fallback_row
                and hasattr(fallback_row, "value")
                and isinstance(fallback_row.value, str)
                and fallback_row.value.strip()
            ):
                fallback = fallback_row.value.strip()
        except Exception:
            pass
    else:
        try:
            with SessionLocal() as session:
                active_row = session.get(AppSetting, SETTING_ACTIVE_MODEL)
                if (
                    active_row
                    and hasattr(active_row, "value")
                    and isinstance(active_row.value, str)
                    and active_row.value.strip()
                ):
                    active = active_row.value.strip()

                fallback_row = session.get(AppSetting, SETTING_FALLBACK_MODEL)
                if (
                    fallback_row
                    and hasattr(fallback_row, "value")
                    and isinstance(fallback_row.value, str)
                    and fallback_row.value.strip()
                ):
                    fallback = fallback_row.value.strip()
        except Exception:
            pass

    return AdminSettingsResponse(active_model=active, fallback_model=fallback)


def update_admin_settings(
    update: AdminSettingsUpdate,
    db: Session,
    settings: Optional[Settings] = None,
) -> AdminSettingsResponse:
    """Update active and/or fallback model in app_settings table and commit immediately.

    Returns the updated AdminSettingsResponse.
    """
    if update.active_model is not None:
        active_row = db.get(AppSetting, SETTING_ACTIVE_MODEL)
        if active_row is None:
            active_row = AppSetting(key=SETTING_ACTIVE_MODEL, value=update.active_model)
            db.add(active_row)
        else:
            active_row.value = update.active_model

    if update.fallback_model is not None:
        fallback_row = db.get(AppSetting, SETTING_FALLBACK_MODEL)
        if fallback_row is None:
            fallback_row = AppSetting(key=SETTING_FALLBACK_MODEL, value=update.fallback_model)
            db.add(fallback_row)
        else:
            fallback_row.value = update.fallback_model

    db.commit()
    return get_admin_settings(db=db, settings=settings)
