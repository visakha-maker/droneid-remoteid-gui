from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

USER_AGENT = "DroneID_RemoteID_GUI/1.0 (Email; contact: visakha@ryderoo.com; Number: +447393867661; webpage: www.ryderoo.com)"

_PROFILE_CONFIGURED = False


def _configure_default_profile():
    global _PROFILE_CONFIGURED
    profile = QWebEngineProfile.defaultProfile()

    if not _PROFILE_CONFIGURED:
        profile.setHttpUserAgent(USER_AGENT)
        _PROFILE_CONFIGURED = True

    return profile


def make_webview(parent=None) -> QWebEngineView:
    web = QWebEngineView(parent)
    profile = _configure_default_profile()
    page = QWebEnginePage(profile, web)
    web.setPage(page)
    return web