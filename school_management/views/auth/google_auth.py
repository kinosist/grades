import secrets
import json
from urllib import parse, request as urllib_request, error as urllib_error

from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from ...models import CustomUser

# Googleの認証エンドポイント
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

def google_login(request):
    """Googleの認証ページにリダイレクト"""
    # ログイン後にリダイレクトするURLを取得。オープンリダイレクト脆弱性対策。
    next_url = request.GET.get('next')
    if not next_url or not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('school_management:dashboard')
    
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
    auth_url = f"{AUTHORIZATION_URL}?{parse.urlencode(params)}"
    return redirect(auth_url)

def google_auth_callback(request):
    """Googleからのコールバックを処理"""
    error = request.GET.get('error')
    state = request.GET.get('state')
    expected_state = request.session.pop('oauth_state', None)

    # stateを検証してCSRF攻撃を防ぐ
    if not state or not expected_state or state != expected_state:
        messages.error(request, "不正なリクエストです。再度ログインしてください。")
        return redirect('school_management:login')

    if error:
        messages.error(request, f"Google認証でエラーが発生しました: {error}")
        return redirect('school_management:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, "Google認証に失敗しました。認証コードが取得できませんでした。")
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

    token_payload = parse.urlencode(token_data).encode('utf-8')
    token_req = urllib_request.Request(
        TOKEN_URL,
        data=token_payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    try:
        with urllib_request.urlopen(token_req, timeout=10) as response:
            if response.status != 200:
                error_content = response.read().decode('utf-8')
                messages.error(request, f"Googleのトークン取得に失敗しました: {error_content}")
                return redirect('school_management:login')
            token_json = json.loads(response.read().decode('utf-8'))
    except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as e:
        messages.error(request, f"Google認証中に通信エラーが発生しました: {e}")
        return redirect('school_management:login')
    
    access_token = token_json.get("access_token")
    if not access_token:
        error_description = token_json.get('error_description', '理由不明')
        messages.error(request, f"Google認証に失敗しました: {error_description}")
        return redirect('school_management:login')

    # アクセストークンを使ってユーザー情報を取得
    headers = {"Authorization": f"Bearer {access_token}"}
    user_info_req = urllib_request.Request(USER_INFO_URL, headers=headers)

    try:
        with urllib_request.urlopen(user_info_req, timeout=10) as response:
            if response.status != 200:
                error_content = response.read().decode('utf-8')
                messages.error(request, f"Googleのユーザー情報取得に失敗しました: {error_content}")
                return redirect('school_management:login')
            user_info = json.loads(response.read().decode('utf-8'))
    except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as e:
        messages.error(request, f"Google認証中に通信エラーが発生しました: {e}")
        return redirect('school_management:login')

    email = user_info.get("email")

    if not email:
        messages.error(request, "Googleアカウントからメールアドレスを取得できませんでした。")
        return redirect('school_management:login')

    # メールアドレスが検証済みであることを確認
    if not user_info.get("email_verified"):
        messages.error(request, "Googleアカウントのメールアドレスが未検証のため、ログインできません。")
        return redirect('school_management:login')

    # 取得したメールアドレスでシステム内のユーザーを検索
    try:
        user = CustomUser.objects.get(email__iexact=email)

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
