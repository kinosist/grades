#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from pathlib import Path

# プロジェクトルートディレクトリ
BASE_DIR = Path(__file__).resolve().parent

# Pythonパスに追加
sys.path.insert(0, str(BASE_DIR))

# 仮想環境のsite-packagesを追加（X Serverでの配置に応じて調整）
# 例: /home/USERNAME/ledleith.com/public_html/grades/venv/lib/python3.11/site-packages
VENV_SITE_PACKAGES = BASE_DIR / 'venv' / 'lib' / 'python3.11' / 'site-packages'
if VENV_SITE_PACKAGES.exists():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

# サブディレクトリでの実行用の環境変数設定
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_project.settings_prod')
os.environ.setdefault('SCRIPT_NAME', '/grades')

# DjangoのWSGIアプリケーション
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

# CGI実行
from wsgiref.handlers import CGIHandler
CGIHandler().run(application)
