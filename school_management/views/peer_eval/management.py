import hashlib
import qrcode
from io import BytesIO
import base64
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.middleware.csrf import get_token
from django.urls import reverse
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
    
    # 共通評価フォームへの絶対URLを生成
    common_url = request.build_absolute_uri(reverse('school_management:peer_evaluation_common', args=[session.id]))
    
    # QRコードをサーバーサイドで生成
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(common_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_image = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"

    context = {
        'session': session,
        'token': token,
        'evaluation_url': request.build_absolute_uri(f'/peer-evaluation/{token}/'),
        'common_evaluation_url': common_url,
        'qr_image': qr_image,
    }
    return render(request, 'school_management/peer_evaluation_link.html', context)
