from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from ...models import StudentQRCode
from .utils import generate_qr_code_image

@login_required
def student_qr_code_view(request):
    """学生用QRコード表示"""
    if not request.user.is_student:
        messages.error(request, '学生のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    qr_code, created = StudentQRCode.objects.get_or_create(student=request.user, defaults={'is_active': True})
    scans = qr_code.scans.select_related('scanned_by').order_by('-scanned_at')
    
    context = {
        'qr_code': qr_code,
        'scans': scans,
        'qr_image': generate_qr_code_image(qr_code.qr_code_url),
        'total_points': scans.aggregate(total=models.Sum('points_awarded'))['total'] or 0,
    }
    return render(request, 'school_management/student_qr_code.html', context)