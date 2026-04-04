from datetime import date
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from ...models import ClassRoom, StudentQRCode, QRCodeScan, LessonSession, PointColumn, StudentColumnScore, Quiz, QuizScore

logger = logging.getLogger(__name__)

@login_required
def qr_code_scan(request, qr_code_id):
    """QRコードスキャン処理（先生専用）"""
    try:
        qr_code = get_object_or_404(StudentQRCode, qr_code_id=qr_code_id, is_active=True)
        
        if not request.user.is_teacher:
            messages.error(request, 'QRコードのスキャンは先生のみ可能です。')
            return redirect('school_management:student_dashboard')
        
        # 1. セッションIDやクラスIDを取得
        session_id = request.GET.get('session_id') or request.POST.get('session_id')
        class_id = request.GET.get('class_id') or request.POST.get('class_id')
        
        current_session = None
        target_classroom = None
        
        if session_id:
            try:
                current_session = LessonSession.objects.get(id=session_id, classroom__teachers=request.user)
                target_classroom = current_session.classroom
            except LessonSession.DoesNotExist:
                pass
        
        if not target_classroom and class_id:
            try:
                target_classroom = ClassRoom.objects.get(id=class_id, teachers=request.user)
            except ClassRoom.DoesNotExist:
                pass

        # 2. セッション・クラス指定がない場合、学生の所属クラスから探す
        if not target_classroom:
            target_classroom = ClassRoom.objects.filter(students=qr_code.student, teachers=request.user).first()
            
        if target_classroom and not current_session:
            today = timezone.now().date()
            current_session = LessonSession.objects.filter(classroom=target_classroom, date=today).order_by('-created_at').first()

        if request.method == 'POST':
            point_type = request.POST.get('point_type', 'qr_action')
            try:
                points_to_add = int(request.POST.get('points', 1))
            except ValueError:
                points_to_add = 1

            posted_session_id = request.POST.get('session_id')
            selected_session = None
            if posted_session_id:
                selected_session = LessonSession.objects.filter(id=posted_session_id, classroom=target_classroom).first()

            added_target = ""

            if point_type == 'qr_action':
                scan = QRCodeScan.objects.create(
                    qr_code=qr_code, 
                    scanned_by=request.user,
                    lesson_session=selected_session
                )
                if scan.points_awarded != points_to_add:
                    scan.points_awarded = points_to_add
                    scan.save(update_fields=['points_awarded'])
                
                added_target = "QRアクション点 (小テスト枠)"
                messages.success(request, f'{qr_code.student.full_name}さんにQRアクション点（{points_to_add}pt）を付与しました。')
            elif point_type.startswith('custom_'):
                column_id = point_type.split('_')[1]
                column = get_object_or_404(PointColumn, id=column_id, classroom=target_classroom)
                score_obj, created = StudentColumnScore.objects.get_or_create(
                    student=qr_code.student,
                    column=column,
                    defaults={'score': 0}
                )
                score_obj.score += points_to_add
                score_obj.save()
                added_target = f"独自項目: {column.column_title}"
                messages.success(request, f'{qr_code.student.full_name}さんの「{column.column_title}」に{points_to_add}ptを追加しました。')
                
            qr_code.last_used_at = timezone.now()
            qr_code.save()

            context = {
                'success': True,
                'qr_code': qr_code,
                'target_classroom': target_classroom,
                'selected_session': selected_session,
                'added_target': added_target,
                'points_added': points_to_add,
            }
            return render(request, 'school_management/qr_code_scan.html', context)
        
        # GET: 設定画面表示
        default_points = target_classroom.qr_point_value if target_classroom else 1
        custom_columns = target_classroom.point_columns.all() if target_classroom else []
        sessions = LessonSession.objects.filter(classroom=target_classroom).order_by('-session_number') if target_classroom else []

        context = {
            'qr_code': qr_code,
            'target_classroom': target_classroom,
            'current_session': current_session,
            'sessions': sessions,
            'custom_columns': custom_columns,
            'default_points': default_points,
        }
        return render(request, 'school_management/qr_code_scan.html', context)
        
    except Exception as e:
        logger.error(f"QRコードスキャンエラー: {e}", exc_info=True)
        context = {'qr_code': None, 'error_message': f'QRコードのスキャンに失敗しました: {str(e)}'}
        return render(request, 'school_management/qr_code_scan.html', context)