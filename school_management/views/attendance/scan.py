from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from ...models import ClassRoom, StudentQRCode, QRCodeScan, LessonSession, StudentLessonPoints, StudentClassPoints

@login_required
def qr_code_scan(request, qr_code_id):
    """QRコードスキャン処理（先生専用）"""
    try:
        qr_code = get_object_or_404(StudentQRCode, qr_code_id=qr_code_id, is_active=True)
        
        if not request.user.is_teacher:
            messages.error(request, 'QRコードのスキャンは先生のみ可能です。')
            return redirect('school_management:student_dashboard')
        
        class_id = request.GET.get('class_id')
        target_classroom = None
        if class_id:
            try:
                target_classroom = ClassRoom.objects.get(id=class_id, teachers=request.user)
            except ClassRoom.DoesNotExist:
                pass
        
        today = date.today()
        current_session = None
        
        if target_classroom:
            teacher_sessions = LessonSession.objects.filter(classroom=target_classroom, date=today).order_by('-created_at')
        else:
            teacher_sessions = LessonSession.objects.filter(classroom__teachers=request.user, date=today).order_by('-created_at')
        
        if teacher_sessions.exists():
            current_session = teacher_sessions.first()
        
        QRCodeScan.objects.create(
            qr_code=qr_code, scanned_by=request.user,
            lesson_session=current_session, points_awarded=1
        )
        
        update_classroom = current_session.classroom if current_session else target_classroom
        if update_classroom:
            if current_session:
                slp, _ = StudentLessonPoints.objects.get_or_create(
                    student=qr_code.student, lesson_session=current_session, defaults={'points': 0}
                )
                slp.points += 1
                slp.save()

            try:
                scp, _ = StudentClassPoints.objects.get_or_create(
                    student=qr_code.student, classroom=update_classroom, defaults={'points': 0}
                )
                scp.points += 1
                scp.save()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f'クラスポイント更新エラー: {str(e)}')
        
        qr_code.last_used_at = timezone.now()
        qr_code.save()
        
        user_scan_count = QRCodeScan.objects.filter(scanned_by=request.user).count()
        student_class_points = 0
        if update_classroom:
            try:
                student_class_points = StudentClassPoints.objects.get(student=qr_code.student, classroom=update_classroom).points
            except StudentClassPoints.DoesNotExist:
                pass
        
        context = {
            'qr_code': qr_code,
            'lesson_session': current_session,
            'scan_time': timezone.now().strftime('%Y年%m月%d日 %H:%M'),
            'user_scan_count': user_scan_count,
            'classroom': update_classroom,
            'student_class_points': student_class_points,
            'points_added': bool(update_classroom),
        }
        return render(request, 'school_management/qr_code_scan.html', context)
        
    except Exception as e:
        context = {'qr_code': None, 'error_message': f'QRコードのスキャンに失敗しました: {str(e)}'}
        return render(request, 'school_management/qr_code_scan.html', context)