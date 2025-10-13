# Railway デプロイ手順

このガイドでは、学校管理システムをRailwayにデプロイする手順を説明します。

## 前提条件

- GitHubアカウント
- Railwayアカウント（https://railway.app/ で無料登録）
- このリポジトリがGitHubにプッシュされていること

## デプロイ手順

### 1. GitHubリポジトリの準備

まず、変更をGitHubにプッシュします：

```powershell
git add .
git commit -m "Add Railway deployment configuration"
git push origin main
```

### 2. Railwayプロジェクトの作成

1. https://railway.app/ にアクセスしてログイン
2. "New Project" をクリック
3. "Deploy from GitHub repo" を選択
4. あなたのリポジトリ（grades）を選択
5. Railwayが自動的にデプロイを開始します

### 3. PostgreSQLデータベースの追加

1. Railwayのプロジェクトダッシュボードで "New" をクリック
2. "Database" → "Add PostgreSQL" を選択
3. データベースが自動的に作成され、`DATABASE_URL` 環境変数が設定されます

### 4. 環境変数の設定

Railwayのプロジェクトダッシュボードで、あなたのサービスをクリックし、"Variables" タブを開きます：

**必須の環境変数：**

```
SECRET_KEY=ランダムな50文字以上の文字列
DEBUG=False
ALLOWED_HOSTS=*.railway.app
```

**SECRET_KEYの生成方法：**

ローカルで以下のコマンドを実行：

```powershell
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5. データベースのマイグレーション

Railwayのダッシュボードで、一度デプロイが完了したら：

1. サービスをクリック
2. "Settings" タブを開く
3. 下にスクロールして "Deploy" セクションを見つける
4. もしくは、ローカルでRailway CLIを使用：

```powershell
# Railway CLIのインストール
npm i -g @railway/cli

# Railwayにログイン
railway login

# プロジェクトにリンク
railway link

# マイグレーションを実行
railway run python manage.py migrate

# スーパーユーザーを作成
railway run python manage.py createsuperuser
```

### 6. カスタムドメインの設定（オプション）

1. サービスの "Settings" タブを開く
2. "Networking" セクションで "Generate Domain" をクリック
3. `yourdomain.railway.app` のようなURLが生成されます
4. 独自ドメインを使用する場合は、"Custom Domain" から設定できます

### 7. 静的ファイルの収集

デプロイ時に自動的に実行されますが、手動で実行する場合：

```powershell
railway run python manage.py collectstatic --noinput
```

## デプロイ後の確認

1. 生成されたURLにアクセス（例：`https://yourapp.railway.app/`）
2. ログインページが表示されることを確認
3. `/admin/` にアクセスして管理画面が動作することを確認

## トラブルシューティング

### デプロイが失敗する場合

1. Railwayのログを確認：
   - サービスをクリック → "Deployments" タブ → 最新のデプロイをクリック
   - ビルドログとランタイムログを確認

2. 環境変数が正しく設定されているか確認

3. データベースが正しく接続されているか確認

### 静的ファイル（CSS/JS）が表示されない場合

**重要**: `nixpacks.toml`ファイルがビルド時に`collectstatic`を自動実行します。

1. `DEBUG=False` が設定されていることを確認
2. WhiteNoiseが正しくインストールされていることを確認
3. デプロイログで`collectstatic`が実行されていることを確認
4. 手動で実行する場合：
   ```powershell
   railway run python manage.py collectstatic --noinput
   ```

### データベース接続エラー

1. PostgreSQLサービスが起動していることを確認
2. `DATABASE_URL` 環境変数が自動的に設定されていることを確認

## 更新のデプロイ

コードを更新した後：

```powershell
git add .
git commit -m "更新内容の説明"
git push origin main
```

Railwayが自動的に新しいバージョンをデプロイします。

## コスト管理

- Railwayの無料枠：月$5のクレジット
- 小規模なアプリケーションなら無料枠内で運用可能
- 使用状況はダッシュボードで確認できます

## セキュリティのベストプラクティス

1. `SECRET_KEY` は絶対に公開しない
2. `DEBUG=False` を本番環境で設定
3. 定期的にバックアップを取る
4. 強力なパスワードを使用
5. HTTPS接続を使用（Railwayはデフォルトで提供）

## サポート

問題が発生した場合：
- Railwayのドキュメント：https://docs.railway.app/
- Railwayのコミュニティ：https://discord.gg/railway
