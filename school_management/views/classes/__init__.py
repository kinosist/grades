"""
クラス管理に関するビューを統合する初期化モジュール

機能ごとに分割されたファイル（list.py, detail.py, management.py）から
各ビュー関数をインポートし、外部（urls.pyなど）から
`classes.関数名` の形でシンプルに呼び出せるようにする役割を持つ。
"""

from .list import class_list_view
from .detail import (
    class_detail_view,
    add_point_column,     # 独自の評価項目（列）を追加する関数
    delete_point_column   # 独自の評価項目（列）を削除する関数
)
from .management import class_create_view, class_delete_view