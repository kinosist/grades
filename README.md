# 学校管理システム

## 概要
教員向けの学校管理システムです。クラス管理、学生管理、授業回管理、小テスト管理、ピア評価などの機能を提供します。

## 技術スタック
- **Python**: 3.11+
- **Django**: 5.2.5
- **uv**: パッケージ管理ツール
- **SQLite**: データベース

## 機能一覧

### 教員機能
- 教員マスタ管理（管理者/担当教員/TA権限）
- ログイン・認証
- ダッシュボード

### クラス管理
- クラス一覧/作成
- 名簿管理（学生の追加・削除）
- 担当教員の設定

### 学生管理
- 学生マスタ管理
- 学生情報の登録・編集

### 授業回管理
- 授業回一覧/作成（第1回〜第15回）
- 日付、トピック設定
- 小テスト・ピア評価フラグ

### グループ管理
- 授業回別グループ編成
- グループメンバー・役割管理

### 小テスト管理
- 小テスト作成・編集
- 採点方式設定（合否/数値入力/ルーブリック）
- QRカメラ巡回採点
- クイックボタン機能

### ピア評価
- 匿名ピア評価フォーム（学生用）
- グループ間順位付け（1位・2位選択）
- グループ内貢献度評価（1〜5段階）

## セットアップ手順

### 1. 環境構築
```powershell
# uvによる仮想環境作成と依存関係インストール
uv sync

# データベースマイグレーション
uv run python manage.py migrate

# 管理者ユーザー作成（既に作成済み）
# Email: test@example.com
# Password: 作成時に設定したパスワード
```

### 2. サーバー起動
```powershell
uv run python manage.py runserver
```

### 3. アクセス
- **Webアプリケーション**: http://127.0.0.1:8000/
- **管理画面**: http://127.0.0.1:8000/admin/

### デフォルトアカウント
- **メールアドレス**: test@example.com
- **パスワード**: 作成時に設定したパスワード
- **権限**: 管理者

## ディレクトリ構造
```
school_system/
├── manage.py
├── pyproject.toml              # uv設定・依存関係
├── school_project/             # Django設定
│   ├── settings.py
│   └── urls.py
└── school_management/          # メインアプリケーション
    ├── models.py              # データモデル
    ├── views.py               # ビュー
    ├── urls.py                # URLパターン
    ├── admin.py               # 管理画面設定
    └── templates/             # HTMLテンプレート
```

## データベースモデル

### 主要モデル
- **Teacher**: 教員マスタ（カスタムユーザーモデル）
- **Student**: 学生マスタ
- **ClassRoom**: クラス
- **LessonSession**: 授業回
- **Group**: グループ
- **Quiz**: 小テスト
- **QuizScore**: 小テスト採点結果
- **PeerEvaluation**: ピア評価
- **ContributionEvaluation**: グループ内貢献度評価

## 使用方法

### 基本的な使用フロー
1. **ログイン**: 教員アカウントでログイン
2. **クラス作成**: 新年度のクラスを作成
3. **学生登録**: 学生マスタに学生を登録
4. **名簿管理**: クラスに学生を追加
5. **授業回作成**: 各回の授業を設定
6. **グループ編成**: 授業回別にグループを作成
7. **小テスト作成**: 必要に応じて小テストを設定
8. **採点**: QRコード読み取りで巡回採点
9. **ピア評価**: 学生に評価用URLを共有

### 管理画面の活用
Django管理画面 (http://127.0.0.1:8000/admin/) では、すべてのデータを直接編集できます。

## 開発用コマンド

### マイグレーション
```powershell
# マイグレーションファイル作成
uv run python manage.py makemigrations

# マイグレーション適用
uv run python manage.py migrate
```

### データ管理
```powershell
# データベースシェル
uv run python manage.py dbshell

# Pythonシェル
uv run python manage.py shell
```

## 本番環境へのデプロイ（Railway）

このアプリケーションは[Railway](https://railway.app/)にデプロイ可能です。

### デプロイ済み環境

- **本番URL**: https://grades-production-e365.up.railway.app/
- **ホスティング**: Railway
- **データベース**: PostgreSQL
- **静的ファイル配信**: WhiteNoise

### デプロイ手順

詳細な手順は[DEPLOYMENT.md](DEPLOYMENT.md)を参照してください。

#### 簡易手順

1. **GitHubにプッシュ**
   ```powershell
   git add .
   git commit -m "Update"
   git push origin main
   ```

2. **Railwayでプロジェクト作成**
   - https://railway.app/ にアクセス
   - "New Project" → "Deploy from GitHub repo"
   - リポジトリを選択

3. **PostgreSQLデータベースを追加**
   - "New" → "Database" → "Add PostgreSQL"

4. **環境変数を設定**

   Appサービスの「Variables」タブで以下を設定：

   **必須の環境変数:**
   ```
   DATABASE_URL=<PostgreSQLサービスから参照で追加>
   SECRET_KEY=<ランダムな50文字以上の文字列>
   DEBUG=False
   ```

   **管理者アカウント用（推奨）:**
   ```
   ADMIN_EMAIL=admin@example.com
   ADMIN_PASSWORD=<安全なパスワード>
   ADMIN_NAME=管理者
   ```

   **DATABASE_URLの設定方法:**
   - 「+ New Variable」→「Add Reference」をクリック
   - Variable Name: `DATABASE_URL`
   - Service: `postgres` (PostgreSQLサービスを選択)
   - Variable: `DATABASE_URL`

   **SECRET_KEYの生成方法:**
   ```powershell
   uv run python generate_secret_key.py
   ```

   **注意:** `ALLOWED_HOSTS`は自動設定されるため不要です

5. **自動デプロイ**
   - GitHubへのプッシュで自動的にデプロイされます
   - デプロイ時に自動的に以下が実行されます：
     - 静的ファイルの収集
     - データベースマイグレーション
     - 管理者ユーザーの作成

### 本番環境の管理者アカウント

Railway環境変数で設定した以下の情報でログインできます：
- **メールアドレス**: `ADMIN_EMAIL`で設定した値
- **パスワード**: `ADMIN_PASSWORD`で設定した値

### トラブルシューティング

#### データが再デプロイ後に消える
- **原因**: `DATABASE_URL`が設定されていない（SQLiteを使用している）
- **解決**: PostgreSQLサービスを追加し、`DATABASE_URL`を参照で設定

#### CSSが表示されない
- **解決**: WhiteNoiseが正しく設定されているか確認

#### ログインできない
- **解決**: 環境変数（ADMIN_EMAIL、ADMIN_PASSWORD）が設定されているか確認

#### CSRF検証エラー
- **解決**: `CSRF_TRUSTED_ORIGINS`が正しく設定されているか確認（通常は自動設定）

詳細は[DEPLOYMENT.md](DEPLOYMENT.md)のトラブルシューティングセクションを参照してください。

## 注意事項
- 開発環境ではSQLite、本番環境ではPostgreSQLを使用します
- パスワードは強固なものに設定してください
- 本番環境では`DEBUG=False`を必ず設定してください
- 定期的なデータベースバックアップを推奨します
- SECRET_KEYは絶対に公開しないでください

## ライセンス
このプロジェクトはMITライセンスの下で公開されています。
