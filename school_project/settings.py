"""
Django settings for school_project - AUTO SELECTOR

開発環境と本番環境を自動で切り替えます
"""

import os

# 環境判定
if os.environ.get('DJANGO_SETTINGS_MODULE') == 'school_project.settings_prod':
    from .settings_prod import *
else:
    from .settings_dev import *
