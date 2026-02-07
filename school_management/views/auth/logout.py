from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages

def logout_view(request):
    """ログアウト"""
    logout(request)
    messages.info(request, 'ログアウトしました。')
    return redirect('school_management:login')