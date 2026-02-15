from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.db import models
# モデルのインポート
from ...models import ClassRoom, Student, StudentQRCode, StudentClassPoints
from .utils import generate_qr_code_image

@login_required
def qr_code_list(request):
    """QRコード管理 - クラス選択（教員用）"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    classrooms = ClassRoom.objects.filter(teachers=request.user)
    
    class_data = []
    for classroom in classrooms:
        student_count = classroom.students.count()
        students = classroom.students.all()
        total_scans = 0
        for student in students:
            qr_code = StudentQRCode.objects.filter(student=student).first()
            if qr_code:
                total_scans += qr_code.scans.count()
        
        class_data.append({
            'classroom': classroom,
            'student_count': student_count,
            'total_scans': total_scans,
        })
    
    context = {'classes': class_data}
    return render(request, 'school_management/qr_code_list.html', context)

@login_required
def class_qr_codes(request, class_id):
    """クラス別QRコード表示"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    classroom = get_object_or_404(ClassRoom, id=class_id)
    if request.user not in classroom.teachers.all():
        messages.error(request, '権限がありません。')
        return redirect('school_management:dashboard')
    
    students = classroom.students.all()
    qr_codes = []
    for student in students:
        qr_code, created = StudentQRCode.objects.get_or_create(student=student, defaults={'is_active': True})
        scan_url = request.build_absolute_uri(
            reverse('school_management:qr_code_scan', kwargs={'qr_code_id': qr_code.qr_code_id})
        ) + f'?class_id={class_id}'
        
        try:
            class_points = StudentClassPoints.objects.get(student=student, classroom=classroom).points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        qr_codes.append({
            'student': student,
            'qr_code': qr_code,
            'scan_count': qr_code.scans.count(),
            'qr_image': generate_qr_code_image(scan_url),
            'class_points': class_points
        })
    
    context = {'classroom': classroom, 'qr_codes': qr_codes}
    return render(request, 'school_management/class_qr_codes.html', context)

@login_required
def qr_code_detail(request, student_id):
    """学生のQRコード詳細表示"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    student = get_object_or_404(Student, id=student_id)
    qr_code, created = StudentQRCode.objects.get_or_create(student=student, defaults={'is_active': True})
    
    scans = qr_code.scans.select_related('scanned_by').order_by('-scanned_at')
    scan_url = request.build_absolute_uri(
        reverse('school_management:qr_code_scan', kwargs={'qr_code_id': qr_code.qr_code_id})
    )
    
    class_id = request.GET.get('class_id')
    classroom = None
    if class_id:
        try:
            classroom = ClassRoom.objects.get(id=class_id)
        except ClassRoom.DoesNotExist:
            pass
    
    context = {
        'student': student,
        'qr_code': qr_code,
        'scans': scans,
        'qr_image': generate_qr_code_image(scan_url),
        'total_points': scans.aggregate(total=models.Sum('points_awarded'))['total'] or 0,
        'classroom': classroom,
    }
    return render(request, 'school_management/qr_code_detail.html', context)