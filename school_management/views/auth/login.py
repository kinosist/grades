from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token

def login_view(request):
    """ログイン画面"""
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        remember = request.POST.get('remember')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            if not remember:
                request.session.set_expiry(0)  # ブラウザ終了でセッション切れる
            messages.success(request, f'ようこそ、{user.full_name}さん！')
            
            # 役割に応じたリダイレクト
            if user.role == 'admin':
                return redirect('school_management:admin_teacher_management')
            elif user.is_teacher:
                return redirect('school_management:dashboard')
            elif user.is_student:
                return redirect('school_management:student_dashboard')
            else:
                return redirect('school_management:dashboard')
        else:
            messages.error(request, 'メールアドレスまたはパスワードが正しくありません。')
    
    return render(request, 'school_management/login_temp.html', {'csrf_token': csrf_token})

@csrf_exempt
def debug_login_view(request):
    """デバッグ用ログイン（CSRF無効）"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'ようこそ、{user.full_name}さん！')
            return redirect('school_management:dashboard')
        else:
            messages.error(request, 'メールアドレスまたはパスワードが正しくありません。')
    
    return render(request, 'school_management/login_temp.html')