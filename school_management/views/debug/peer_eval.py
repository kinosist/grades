import uuid
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, Http404
from django.db import transaction
from django.conf import settings

from school_management.models import (
    ClassRoom, Student, LessonSession, PeerEvaluation, ContributionEvaluation, StudentClassPoints
)

@login_required
def debug_peer_eval(request, class_id):
    """
    ピア評価の成績計算ロジック検証用ビュー。
    任意の点数を入力し、それを元に再計算した結果を返す。
    トランザクションとロールバックを用いることで本番データへの影響を防ぐ。
    """
    if not getattr(settings, 'ENABLE_DEBUG_VIEWS', False):
        raise Http404("デバッグ画面は無効化されています。")
        
    if not request.user.is_superuser and request.user.role != 'admin':
        return HttpResponseForbidden("このページにはアクセスできません。管理者専用のデバッグ機能です。")

    classroom = get_object_or_404(ClassRoom, id=class_id)
    students = Student.objects.filter(classroom=classroom, role='student').order_by('student_number')
    
    results = []
    
    # 計算前の元のデータを取得しておく
    original_points_map = {}
    for student in students:
        scp = StudentClassPoints.objects.filter(student=student, classroom=classroom).first()
        if scp:
            original_points_map[student.id] = {
                'activity_points': scp.total_activity_points,
                'class_points': scp.class_points,
                'total_points': scp.total_points,
            }
        else:
            original_points_map[student.id] = {
                'activity_points': 0,
                'class_points': 0,
                'total_points': 0,
            }

    if request.method == 'POST':
        # トランザクションを開始し、最後に必ずロールバックする
        with transaction.atomic():
            # 1. 現在のピア評価データを無効化（クリア）
            LessonSession.objects.filter(classroom=classroom).update(
                peer_evaluation_status=LessonSession.PeerEvaluationStatus.NOT_OPEN
            )
            PeerEvaluation.objects.filter(lesson_session__classroom=classroom).delete()
            
            # 2. 検証用のダミーセッションを作成
            dummy_session = LessonSession.objects.create(
                classroom=classroom, 
                session_number=999, 
                has_peer_evaluation=True,
                peer_evaluation_status=LessonSession.PeerEvaluationStatus.CLOSED
            )
            dummy_pe = PeerEvaluation.objects.create(
                lesson_session=dummy_session, 
                evaluator_token=uuid.uuid4()
            )
            
            # 3. 画面からの入力値をContributionEvaluationとして登録
            for student in students:
                score_str = request.POST.get(f"score_{student.id}")
                if score_str and score_str.strip() and score_str.lstrip('-').isdigit():
                    score = int(score_str)
                    ContributionEvaluation.objects.create(
                        peer_evaluation=dummy_pe,
                        evaluatee=student,
                        contribution_score=score
                    )
            
            # 4. 全生徒の成績を再計算
            for student in students:
                scp, created = StudentClassPoints.objects.get_or_create(
                    student=student, 
                    classroom=classroom
                )
                
                scp.calculate_points_internal()
                scp.save()
                
                input_score = request.POST.get(f"score_{student.id}", "")
                original = original_points_map[student.id]
                diff = scp.total_points - original['total_points']
                
                results.append({
                    'student': student,
                    'input_score': input_score,
                    'original': original,
                    'activity_points': scp.total_activity_points,
                    'class_points': scp.class_points,
                    'total_points': scp.total_points,
                    'diff': diff,
                })
            
            # 5. 強制ロールバック
            transaction.set_rollback(True)
            
            context = {
                'classroom': classroom,
                'results': results,
                'is_simulated': True,
            }
            return render(request, 'school_management/debug_peer_eval.html', context)
            
    else:
        # GETリクエスト：現在の計算済み成績を表示
        for student in students:
            original = original_points_map[student.id]
            results.append({
                'student': student,
                'input_score': '',
                'original': original,
                'activity_points': original['activity_points'],
                'class_points': original['class_points'],
                'total_points': original['total_points'],
            })
            
        context = {
            'classroom': classroom,
            'results': results,
            'is_simulated': False,
        }
        return render(request, 'school_management/debug_peer_eval.html', context)
