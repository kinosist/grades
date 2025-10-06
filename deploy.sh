#!/bin/bash
# X Server デプロイスクリプト
# Git pull後に実行する自動デプロイスクリプト

set -e  # エラーが発生したら停止

echo "=========================================="
echo "School Management System - デプロイ開始"
echo "=========================================="

# カレントディレクトリを確認
echo "📁 現在のディレクトリ: $(pwd)"

# Gitから最新コードを取得
echo ""
echo "📥 最新コードを取得中..."
git pull origin main

# 仮想環境をアクティベート
echo ""
echo "🐍 仮想環境をアクティベート中..."
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ 仮想環境: $(which python)"
else
    echo "❌ エラー: venv が見つかりません"
    echo "   以下のコマンドで作成してください："
    echo "   python3 -m venv venv"
    exit 1
fi

# 依存関係のインストール
echo ""
echo "📦 依存関係をインストール中..."
pip install -r requirements.txt --quiet

# データベースマイグレーション
echo ""
echo "🗄️  データベースマイグレーション実行中..."
python manage.py migrate --noinput

# 静的ファイルの収集
echo ""
echo "📂 静的ファイルを収集中..."
python manage.py collectstatic --noinput --clear

# 権限設定の確認と修正
echo ""
echo "🔐 ファイル権限を設定中..."
chmod 755 index.cgi
chmod 666 db.sqlite3 2>/dev/null || true
chmod 755 . 2>/dev/null || true

# デプロイ完了
echo ""
echo "=========================================="
echo "✅ デプロイが完了しました！"
echo "=========================================="
echo ""
echo "🌐 アクセスURL: https://ledleith.com/grades/"
echo ""
echo "📊 デプロイ情報:"
echo "   - ブランチ: $(git branch --show-current)"
echo "   - コミット: $(git log -1 --pretty=format:'%h - %s')"
echo "   - 日時: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
