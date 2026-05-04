import secrets
import requests
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from ...models import CustomUser

# Googleの認証エンドポイント
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

def google_login(request):
    """Googleの認証ページにリダイレクト"""
    # ログイン後にリダイレクトするURLを取得。なければダッシュボードへ。
    next_url = request.GET.get('next', reverse('school_management:dashboard'))
    
    # CSRF対策のstateを生成してセッションに保存
    state = secrets.token_urlsafe(16)
    request.session['oauth_state'] = state
    request.session['oauth_next'] = next_url

    # Google認証後のリダイレクト先URIを生成
    redirect_uri = request.build_absolute_uri(reverse('school_management:google_auth_callback'))

    # Google認証用のパラメータを作成
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    
    # 認証URLを組み立ててリダイレクト
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    auth_url = f"{AUTHORIZATION_URL}?{query_string}"
    return redirect(auth_url)

def google_auth_callback(request):
    """Googleからのコールバックを処理"""
    code = request.GET.get('code')
    state = request.GET.get('state')
    
    # stateを検証してCSRF攻撃を防ぐ
    if state != request.session.get('oauth_state'):
        messages.error(request, "不正なリクエストです。")
        return redirect('school_management:login')

    redirect_uri = request.build_absolute_uri(reverse('school_management:google_auth_callback'))

    # 認証コードを使ってアクセストークンを取得
    token_data = {
        "code": code,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    token_response = requests.post(TOKEN_URL, data=token_data)
    token_json = token_response.json()
    
    access_token = token_json.get("access_token")
    if not access_token:
        messages.error(request, "Google認証に失敗しました。")
        return redirect('school_management:login')

    # アクセストークンを使ってユーザー情報を取得
    headers = {"Authorization": f"Bearer {access_token}"}
    user_info_response = requests.get(USER_INFO_URL, headers=headers)
    user_info = user_info_response.json()
    email = user_info.get("email")

    if not email:
        messages.error(request, "Googleアカウントからメールアドレスを取得できませんでした。")
        return redirect('school_management:login')

    # 取得したメールアドレスでシステム内のユーザーを検索
    try:
        user = CustomUser.objects.get(email=email)
        
        # 教員または管理者のみログインを許可
        if user.is_teacher:
            login(request, user)
            messages.success(request, f"ようこそ、{user.full_name}さん！")
            next_url = request.session.pop('oauth_next', reverse('school_management:dashboard'))
            return redirect(next_url)
        else:
            messages.error(request, "このアカウントは教員または管理者の権限を持っていません。")
            return redirect('school_management:login')

    except CustomUser.DoesNotExist:
        messages.error(request, f"メールアドレス '{email}' はシステムに登録されていません。")
        return redirect('school_management:login')
