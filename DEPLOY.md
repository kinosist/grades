# X Server デプロイ手順（サブディレクトリ版）

このドキュメントはDjango School Management SystemをX Server（Xserver）の**サブディレクトリ**にデプロイする手順を説明します。

## 🎯 デプロイ先

- **URL**: https://ledleith.com/grades/
- **ドメイン**: ledleith.com（既存WordPressと共存）
- **配置場所**: `/home/USERNAME/ledleith.com/public_html/grades/`

## 📋 前提条件

- X Serverアカウント（スタンダードプラン以上推奨）
- Python 3.11以上がサーバーで利用可能
- SSH接続可能なアカウント
- データベースファイルの書き込み権限
- ledleith.comドメインでWordPressが稼働中

## 🚀 デプロイ方法

このプロジェクトは**2つのデプロイ方法**があります：

### 方法A: Git連携デプロイ（推奨）
Git経由で自動デプロイ。更新が簡単です。

### 方法B: FTP/SCP手動デプロイ
ファイルを直接アップロード。初回のみ推奨。

---

## 🔄 方法A: Git連携デプロイ（推奨）

### 初回セットアップ

#### 1. SSH接続

```bash
ssh USERNAME@svXXXX.xserver.jp
cd ~/ledleith.com/public_html/
```

#### 2. Gitリポジトリをクローン

```bash
# grades ディレクトリとしてクローン
git clone https://github.com/YOUR_USERNAME/grades.git grades
cd grades
```

#### 3. ブランチ確認

```bash
git branch -a
git checkout main  # または feature/#5 など
```

#### 4. Python仮想環境の作成

```bash
# Pythonバージョン確認
python3 --version  # 3.11以上必要

# 仮想環境作成
python3 -m venv venv

# 仮想環境アクティベート
source venv/bin/activate

# 依存関係インストール
pip install --upgrade pip
pip install -r requirements.txt
```

#### 5. index.cgiの設定調整

`index.cgi`の16行目を確認し、Pythonバージョンに合わせて調整：

```python
# 例: Python 3.11の場合
VENV_SITE_PACKAGES = BASE_DIR / 'venv' / 'lib' / 'python3.11' / 'site-packages'
```

Pythonバージョン確認方法：
```bash
python3 --version
# 出力例: Python 3.11.5 → python3.11を使用
```

#### 6. デプロイスクリプトの実行

```bash
# デプロイスクリプトに実行権限を付与
chmod +x deploy.sh

# 初回デプロイ実行
./deploy.sh
```

このスクリプトが以下を自動実行します：
- Git pull
- 依存関係インストール
- マイグレーション
- 静的ファイル収集
- 権限設定

#### 7. SECRET_KEYの変更（重要）

`school_project/settings_prod.py`を編集：

```python
# ドメイン設定（既に設定済み）
ALLOWED_HOSTS = [
    'ledleith.com',
    'www.ledleith.com',
]

# SECRET_KEY（本番環境では必ず変更）
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'your-new-secret-key-here')
```

SECRET_KEYの生成方法：
```bash
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

#### 8. 管理ユーザー作成

```bash
source venv/bin/activate
python manage.py createsuperuser
```

#### 9. 動作確認

ブラウザで以下にアクセス：

```
https://ledleith.com/grades/
```

正常に動作すれば、ログイン画面が表示されます。

**注意**: WordPressは `https://ledleith.com/` で引き続き動作します。

### 2回目以降の更新（日常運用）

コードを更新した場合は、サーバー上で以下を実行するだけです：

```bash
# SSH接続
ssh USERNAME@svXXXX.xserver.jp
cd ~/ledleith.com/public_html/grades/

# デプロイスクリプト実行
./deploy.sh
```

これだけで以下が自動実行されます：
1. `git pull` で最新コードを取得
2. 依存関係の更新
3. データベースマイグレーション
4. 静的ファイル収集
5. 権限設定

---

## 📦 方法B: FTP/SCP手動デプロイ

Git使用が難しい場合の手動デプロイ方法です。

### 1. ファイルのアップロード

FTPまたはSCPでプロジェクトファイルをアップロードします：

```
/home/USERNAME/ledleith.com/public_html/grades/
├── .htaccess
├── index.cgi
├── requirements.txt
├── manage.py
├── school_project/
├── school_management/
└── static/
```

**注意**: `db.sqlite3`、`venv/`、`staticfiles/`は除外してください。

### 2. SSH接続して環境構築

```bash
ssh USERNAME@svXXXX.xserver.jp
cd ~/ledleith.com/public_html/grades/

# 仮想環境作成
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 実行権限付与
chmod 755 index.cgi

# マイグレーション
python manage.py migrate
python manage.py collectstatic --noinput

# 管理ユーザー作成
python manage.py createsuperuser
```

---

## 🔧 トラブルシューティング

### 500 Internal Server Error

1. **エラーログ確認**
   ```bash
   tail -f ~/ledleith.com/public_html/grades/django_errors.log
   tail -f /home/USERNAME/ledleith.com/log/error_log
   ```

2. **CGI実行権限確認**
   ```bash
   ls -l index.cgi  # 755になっているか
   head -1 index.cgi  # shebangが正しいか
   ```

3. **Pythonパス確認**
   ```bash
   which python3
   # index.cgiの1行目を確認し、必要に応じて修正
   ```

### 静的ファイルが表示されない

```bash
# 静的ファイルディレクトリの権限確認
chmod 755 staticfiles/
chmod 644 staticfiles/**/*

# 再度収集
python manage.py collectstatic --noinput --clear
```

### データベースエラー

```bash
# 権限確認
ls -l db.sqlite3  # 666になっているか
ls -ld .  # 777または755で書き込み可能か

# 権限修正
chmod 666 db.sqlite3
chmod 777 .
```

### モジュールが見つからないエラー

```bash
# 仮想環境の確認
source venv/bin/activate
pip list | grep Django

# 再インストール
pip install -r requirements.txt --force-reinstall
```

## 🔒 セキュリティチェックリスト

- [ ] `DEBUG = False`に設定済み
- [ ] `SECRET_KEY`を変更済み
- [ ] `ALLOWED_HOSTS`を正しく設定済み
- [ ] `.htaccess`で`.py`ファイルへの直接アクセスを禁止済み
- [ ] `db.sqlite3`への直接アクセスを禁止済み
- [ ] HTTPSを有効化（X Serverの設定パネルから）
- [ ] 管理画面のURL変更を検討（オプション）

## 📊 パフォーマンス最適化

### 1. HTTPSを有効化した場合の設定

`settings_prod.py`を編集：

```python
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
```

### 2. 静的ファイルの圧縮（オプション）

```bash
pip install django-compressor
```

### 3. キャッシュ設定（オプション）

`settings_prod.py`に追加：

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': BASE_DIR / 'cache',
    }
}
```

## 🔄 開発ワークフロー

### ローカル開発 → サーバーデプロイの流れ

```bash
# 1. ローカルで開発
cd /path/to/grades
# コード編集...

# 2. ローカルでテスト
uv run python manage.py runserver

# 3. Gitにコミット＆プッシュ
git add .
git commit -m "新機能を追加"
git push origin main

# 4. サーバーでデプロイ
ssh USERNAME@svXXXX.xserver.jp
cd ~/ledleith.com/public_html/grades/
./deploy.sh
```

### Git連携のメリット

✅ コマンド1つでデプロイ完了
✅ バージョン管理で履歴が残る
✅ ロールバックが簡単
✅ チーム開発に対応
✅ FTPアップロードの手間が不要

## 📞 サポート

問題が解決しない場合：

1. X Serverサポートセンターに問い合わせ
2. `django_errors.log`の内容を確認
3. Djangoのドキュメントを参照: https://docs.djangoproject.com/

## 🌐 参考リンク

- [X Server公式マニュアル](https://www.xserver.ne.jp/manual/)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [CGI環境でのDjango実行](https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/)
