"""SECRET_KEY生成スクリプト（Django不要版）"""
import secrets
import string

def generate_secret_key(length=50):
    """Django互換のSECRET_KEYを生成"""
    chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
    return ''.join(secrets.choice(chars) for _ in range(length))

print("=" * 60)
print("Railway用のSECRET_KEYを生成しました:")
print("=" * 60)
print(generate_secret_key())
print("=" * 60)
print("このキーをRailwayの環境変数 'SECRET_KEY' に設定してください")
