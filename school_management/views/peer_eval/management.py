import hashlib
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.middleware.csrf import get_token
from ...models import LessonSession

@login_required 
def peer_evaluation_create_view(request, session_id):
    """ピア評価作成・設定"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        # ピア評価を有効にする
        session.has_peer_evaluation = True
        session.save()
        messages.success(request, 'ピア評価を有効にしました。評価リンクを学生に共有してください。')
        return redirect('school_management:peer_evaluation_list', session_id=session.id)
    
    context = {
        'session': session,
        'csrf_token': csrf_token,
    }
    return render(request, 'school_management/peer_evaluation_create.html', context)

@login_required
def peer_evaluation_link_view(request, session_id):
    """ピア評価リンク生成"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    # 匿名トークン生成
    import hashlib
    token = hashlib.md5(f"peer_{session.id}".encode()).hexdigest()
    
    context = {
        'session': session,
        'token': token,
        'evaluation_url': request.build_absolute_uri(f'/peer-evaluation/{token}/')
    }
    return render(request, 'school_management/peer_evaluation_link.html', context)
