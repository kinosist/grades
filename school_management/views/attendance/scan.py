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
        
        # 1. セッションIDから授業回を特定（優先）
        session_id = request.GET.get('session_id')
        current_session = None
        target_classroom = None
        
        if session_id:
            try:
                current_session = LessonSession.objects.get(id=session_id, classroom__teachers=request.user)
                target_classroom = current_session.classroom
            except LessonSession.DoesNotExist:
                pass
        
        # 2. セッション指定がない場合、クラスIDや日付から推測
        if not current_session:
            class_id = request.GET.get('class_id')
            if class_id:
                try:
                    target_classroom = ClassRoom.objects.get(id=class_id, teachers=request.user)
                except ClassRoom.DoesNotExist:
                    pass
            
            today = date.today()
            if target_classroom:
                teacher_sessions = LessonSession.objects.filter(classroom=target_classroom, date=today).order_by('-created_at')
            else:
                teacher_sessions = LessonSession.objects.filter(classroom__teachers=request.user, date=today).order_by('-created_at')
            
            if teacher_sessions.exists():
                current_session = teacher_sessions.first()
                if not target_classroom:
                    target_classroom = current_session.classroom
        
        # スキャン履歴を作成
        scan = QRCodeScan.objects.create(
            qr_code=qr_code, scanned_by=request.user,
            lesson_session=current_session
            # points_awarded は models.py のシグナルで自動設定されるため省略
        )
        
        update_classroom = current_session.classroom if current_session else target_classroom
        
        qr_code.last_used_at = timezone.now()
        qr_code.save()
        
        user_scan_count = QRCodeScan.objects.filter(scanned_by=request.user).count()
        student_class_points = 0
        if update_classroom:
            try:
                # 評価一覧と同じ「総合ポイント（total_points）」を表示する
                student_class_points = StudentClassPoints.objects.get(student=qr_code.student, classroom=update_classroom).total_points
            except StudentClassPoints.DoesNotExist:
                pass
        
        context = {
            'qr_code': qr_code,
            'lesson_session': current_session,
            'scan_time': timezone.now().strftime('%Y年%m月%d日 %H:%M'),
            'user_scan_count': user_scan_count,
            'classroom': update_classroom,
            'student_class_points': student_class_points,
            # ポイント加算は「授業回」が特定できた場合のみ行われる（models.pyのシグナル仕様）
            'points_added': bool(current_session),
            'points_awarded': scan.points_awarded,
        }
        return render(request, 'school_management/qr_code_scan.html', context)
        
    except Exception as e:
        context = {'qr_code': None, 'error_message': f'QRコードのスキャンに失敗しました: {str(e)}'}
        return render(request, 'school_management/qr_code_scan.html', context)