from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.db import models
from django.views.decorators.http import require_POST
# モデルのインポート
from ...models import ClassRoom, Student, StudentQRCode, StudentClassPoints, LessonSession, QRCodeScan, StudentColumnScore
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
                total_scans += qr_code.scans.filter(scanned_by=request.user).count()
        
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
    session_id = request.GET.get('session_id')
    lesson_session = None
    
    if session_id:
        lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    qr_codes = []
    for student in students:
        qr_code, created = StudentQRCode.objects.get_or_create(student=student, defaults={'is_active': True})
        
        base_url = reverse('school_management:qr_code_scan', kwargs={'qr_code_id': qr_code.qr_code_id})
        params = f'?class_id={class_id}'
        if session_id:
            params += f'&session_id={session_id}'
            
        scan_url = request.build_absolute_uri(base_url) + params
        
        try:
            class_points = StudentClassPoints.objects.get(student=student, classroom=classroom).points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        qr_codes.append({
            'student': student,
            'qr_code': qr_code,
            'scan_count': qr_code.scans.filter(scanned_by=request.user).count(),
            'qr_image': generate_qr_code_image(scan_url),
            'class_points': class_points
        })
    
    context = {'classroom': classroom, 'qr_codes': qr_codes, 'lesson_session': lesson_session}
    return render(request, 'school_management/class_qr_codes.html', context)

@login_required
def qr_code_detail(request, student_id):
    """学生のQRコード詳細表示"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    student = get_object_or_404(Student, id=student_id)
    qr_code, created = StudentQRCode.objects.get_or_create(student=student, defaults={'is_active': True})
    
    scans = qr_code.scans.filter(scanned_by=request.user).select_related('scanned_by', 'lesson_session', 'point_column').order_by('-scanned_at')
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
            
    # スキャン履歴の詳細な集計
    total_qr_action_points = scans.filter(point_column__isnull=True).aggregate(total=models.Sum('points_awarded'))['total'] or 0
    total_qr_action_scans = scans.filter(point_column__isnull=True).count()
    
    custom_points_stats = []
    from django.db.models import Sum, Count
    custom_stats = scans.filter(point_column__isnull=False).values('point_column__column_title').annotate(
        total_points=Sum('points_awarded'),
        scan_count=Count('id')
    ).order_by('point_column__column_title')
    
    for stat in custom_stats:
        custom_points_stats.append({
            'title': stat['point_column__column_title'],
            'points': stat['total_points'],
            'count': stat['scan_count']
        })
    
    context = {
        'student': student,
        'qr_code': qr_code,
        'scans': scans,
        'qr_image': generate_qr_code_image(scan_url),
        'total_points': scans.aggregate(total=models.Sum('points_awarded'))['total'] or 0,
        'total_qr_action_points': total_qr_action_points,
        'total_qr_action_scans': total_qr_action_scans,
        'custom_points_stats': custom_points_stats,
        'classroom': classroom,
    }
    return render(request, 'school_management/qr_code_detail.html', context)

@login_required
def delete_qr_scan(request, scan_id):
    """QRスキャン履歴の削除"""
    if not request.user.is_teacher:
        messages.error(request, '権限がありません。')
        return redirect('school_management:dashboard')
    
    scan = get_object_or_404(QRCodeScan, id=scan_id, scanned_by=request.user)
    student_id = scan.qr_code.student.id
    
    # 独自評価項目のスキャンの場合は、関連するStudentColumnScoreを減算する
    if scan.point_column:
        score_obj = StudentColumnScore.objects.filter(
            student=scan.qr_code.student,
            column=scan.point_column
        ).first()
        if score_obj:
            score_obj.score -= scan.points_awarded
            score_obj.save()
            
    # 削除（シグナルによりポイント再計算が行われる）
    scan.delete()
    
    messages.success(request, 'スキャン履歴を削除しました。ポイントが再計算されました。')
    
    return redirect('school_management:qr_code_detail', student_id=student_id)

@login_required
@require_POST
def bulk_delete_qr_scans(request, student_id):
    """QRスキャン履歴の一括削除"""
    if not request.user.is_teacher:
        messages.error(request, '権限がありません。')
        return redirect('school_management:dashboard')
        
    scan_ids = request.POST.getlist('scan_ids')
    if not scan_ids:
        messages.warning(request, '削除する履歴が選択されていません。')
        return redirect('school_management:qr_code_detail', student_id=student_id)
        
    scans = QRCodeScan.objects.filter(id__in=scan_ids, qr_code__student_id=student_id, scanned_by=request.user)
    
    # 独自評価項目の減算処理
    for scan in scans:
        if scan.point_column:
            score_obj = StudentColumnScore.objects.filter(
                student=scan.qr_code.student,
                column=scan.point_column
            ).first()
            if score_obj:
                score_obj.score -= scan.points_awarded
                score_obj.save()
                
    deleted_count = scans.count()
    scans.delete()
    
    messages.success(request, f'{deleted_count}件のスキャン履歴を削除し、ポイントを再計算しました。')
    return redirect('school_management:qr_code_detail', student_id=student_id)