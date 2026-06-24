from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg
from ...models import (
    CustomUser, ClassRoom, LessonSession, QuizScore, 
    Attendance, GroupMember, PeerEvaluation, StudentClassPoints,
    StudentGoal, SelfEvaluation, LessonReport
)

@login_required
def student_detail_view(request, student_number):
    """学生詳細"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student = get_object_or_404(CustomUser, student_number=student_number, role='student')

    # 削除・解除処理は別ビュー(student_delete_execute_view)に移動しました
    
    # 所属クラス一覧とそれぞれのクラスポイントを取得
    classes = student.classroom_set.filter(teachers=request.user).prefetch_related('teachers')
    
    class_data = []
    for classroom in classes:
        try:
            class_points_obj = StudentClassPoints.objects.get(student=student, classroom=classroom)
            class_points = class_points_obj.class_points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_data.append({
            'classroom': classroom,
            'points': class_points
        })
    
    # 統計情報を計算 (全クラス合計)
    # 1. 小テスト統計 (重複除外)
    all_quiz_scores = QuizScore.objects.filter(
        student=student,
        is_cancelled=False
    ).order_by('graded_at')
    
    unique_scores = {qs.quiz_id: qs.score for qs in all_quiz_scores}
    total_quizzes = len(unique_scores)
    quiz_total_score = sum(unique_scores.values())
    
    scp_list = StudentClassPoints.objects.filter(student=student)
    peer_total_score = 0
    peer_total_count = 0
    for scp in scp_list:
        peer_stats = scp.peer_eval_stats
        peer_total_score += peer_stats.get('total', 0)
        peer_total_count += peer_stats.get('count', 0)
        
    combined_count = total_quizzes + peer_total_count
    combined_score = quiz_total_score + peer_total_score
    avg_score = round(combined_score / combined_count, 1) if combined_count > 0 else 0
    
    # 2. ピア評価回数 (評価した回数)
    student_groups = GroupMember.objects.filter(student=student).values_list('group', flat=True)
    peer_eval_count = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups
    ).count()
    
    # 3. 最近の活動 (小テストとピア評価を合わせた最新5件)
    recent_quizzes = []
    seen_quiz_ids = set()
    desc_quiz_scores = QuizScore.objects.filter(
        student=student,
        is_cancelled=False
    ).select_related('quiz', 'quiz__lesson_session', 'quiz__lesson_session__classroom').order_by('-graded_at')
    
    for qs in desc_quiz_scores:
        if qs.quiz_id not in seen_quiz_ids:
            recent_quizzes.append({
                'type': 'quiz',
                'date': qs.graded_at,
                'title': f"小テスト: {qs.quiz.quiz_name} ({qs.quiz.lesson_session.classroom.class_name})",
                'score': f"{qs.score}点",
                'icon': 'fa-pen-alt',
                'color': 'text-primary'
            })
            seen_quiz_ids.add(qs.quiz_id)
            if len(recent_quizzes) >= 5:
                break
                
    recent_peers = []
    peer_evaluations = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups
    ).select_related('lesson_session', 'lesson_session__classroom').order_by('-created_at')[:5]
    
    for pe in peer_evaluations:
        recent_peers.append({
            'type': 'peer',
            'date': pe.created_at,
            'title': f"ピア評価提出 ({pe.lesson_session.classroom.class_name} 第{pe.lesson_session.session_number}回)",
            'score': "提出済",
            'icon': 'fa-users',
            'color': 'text-success'
        })
        
    recent_activities = sorted(recent_quizzes + recent_peers, key=lambda x: x['date'], reverse=True)[:5]
    
    context = {
        'student': student,
        'classes': classes,
        'class_data': class_data,
        'recent_activities': recent_activities,
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': avg_score,
            'peer_eval_count': peer_eval_count,
        }
    }
    return render(request, 'school_management/student_detail.html', context)

@login_required
def class_student_detail_view(request, class_id, student_number):
    """クラス内の学生詳細"""
    # 担当教師のチェックを追加
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # 学生がこのクラスに所属しているかチェック
    if not classroom.students.filter(student_number=student_number).exists():
        messages.error(request, 'この学生は指定されたクラスに所属していません。')
        return redirect('school_management:class_detail', class_id=class_id)
    
    # クラス内での学生の成績やアクティビティを取得
    class_sessions = LessonSession.objects.filter(classroom=classroom).order_by('-date')
    
    # このクラスでのクイズ成績を取得
    # 授業日が新しい順、かつ採点日時が新しい順に取得（キャンセル済みは除外）
    all_quiz_scores = QuizScore.objects.filter(
        student=student,
        quiz__lesson_session__classroom=classroom,
        is_cancelled=False
    ).select_related('quiz', 'quiz__lesson_session').order_by('-quiz__lesson_session__date', '-graded_at')
    
    # 重複排除: 同じクイズIDなら最新の1件のみをリストに追加
    quiz_scores = []
    seen_quiz_ids = set()
    for score in all_quiz_scores:
        if score.quiz.id not in seen_quiz_ids:
            quiz_scores.append(score)
            seen_quiz_ids.add(score.quiz.id)
            if len(quiz_scores) >= 10:  # 最新10件集まったら終了
                break
    
    # このクラスでの出席記録を取得
    attendance_records = Attendance.objects.filter(
        student=student,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-lesson_session__date')
    
    # このクラスでのピア評価を取得（学生が所属するグループによる評価）
    # まず学生が所属するグループを取得
    student_groups = GroupMember.objects.filter(student=student).values_list('group', flat=True)
    
    peer_evaluations = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-created_at')
    
    # 統計情報を計算
    # StudentClassPointsのメソッドを使用して一貫性を保つ
    try:
        scp = StudentClassPoints.objects.get(student=student, classroom=classroom)
        quiz_stats = scp.quiz_stats
        total_quizzes = quiz_stats['count']
        
        peer_stats = scp.peer_eval_stats
        peer_count = peer_stats['count']
        peer_total = peer_stats['total']
        
        # テストモード（シミュレーション）の場合はセッションからデータを取得して上書き
        sim_data_class = request.session.get('peer_sim_points', {}).get(str(classroom.id), {})
        if request.session.get('test_mode') and sim_data_class:
            sim_total = 0
            sim_count = 0
            for session_id, session_sim in sim_data_class.items():
                if not isinstance(session_sim, dict):
                    continue
                data = session_sim.get(str(student.id))
                if data is None:
                    continue

                if isinstance(data, dict):
                    # For advanced point modes (manual入力時)
                    contrib = float(data.get('contrib', data.get('member', 0)) or 0)
                    group = float(data.get('group_manual', data.get('group', 0)) or 0)
                    sim_total += (contrib + group)
                else:
                    # Legacy fallback
                    sim_total += float(data)
                sim_count += 1

            if sim_count > 0:
                # If we have simulation data, we completely replace the DB peer points with the simulated points for those sessions
                # Note: For simplicity, if test mode is on, we'll just use the simulated total
                peer_total = sim_total
                peer_count = sim_count
            
        total_count = total_quizzes + peer_count
        total_score = quiz_stats.get('total', quiz_stats.get('average', 0) * total_quizzes) + peer_total
        avg_score = round(total_score / total_count, 1) if total_count > 0 else 0
        
    except StudentClassPoints.DoesNotExist:
        total_quizzes = 0
        avg_score = 0
    
    attendance_count = attendance_records.filter(status='present').count()
    total_sessions = class_sessions.count()
    attendance_rate = (attendance_count / total_sessions * 100) if total_sessions > 0 else 0
    
    # 目標・自己評価の取得
    goal = StudentGoal.objects.filter(student=student, classroom=classroom).first()
    self_eval = SelfEvaluation.objects.filter(student=student, classroom=classroom).first()

    # このクラスでの日報一覧（授業回日付順）
    lesson_reports = LessonReport.objects.filter(
        student=student,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('lesson_session__date')

    context = {
        'classroom': classroom,
        'student': student,
        'class_sessions': class_sessions[:5],  # 最新5セッション
        'quiz_scores': quiz_scores,  # 重複排除済みのリスト（最大10件）
        'attendance_records': attendance_records[:10],  # 最新10件の出席記録
        'peer_evaluations': peer_evaluations[:10],  # 最新10件のピア評価
        'goal': goal,
        'self_eval': self_eval,
        'lesson_reports': lesson_reports,
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': round(avg_score, 1),
            'attendance_count': attendance_count,
            'total_sessions': total_sessions,
            'attendance_rate': round(attendance_rate, 1),
        }
    }
    return render(request, 'school_management/class_student_detail.html', context)


@login_required
def student_delete_confirm_view(request, student_number):
    """学生削除確認画面"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # 担当外の学生は削除できないようチェック（必要に応じて）
    if not student.managed_by.filter(id=request.user.id).exists():
        messages.error(request, '担当外の学生の削除はできません。')
        return redirect('school_management:student_list')

    classrooms = student.classroom_set.all()
    classroom_names = [f"{c.get_semester_display()} {c.class_name} ({c.year})" for c in classrooms]
    
    context = {
        'student': student,
        'classrooms': classroom_names,
        'classroom_count': len(classroom_names),
    }
    return render(request, 'school_management/student_delete_confirm.html', context)


@login_required
def student_delete_execute_view(request, student_number):
    """学生削除・担当解除実行"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    if request.method != 'POST':
        return redirect('school_management:student_detail', student_number=student_number)

    student = get_object_or_404(CustomUser, student_number=student_number, role='student', managed_by=request.user)
    delete_type = request.POST.get('delete_type')

    if delete_type == 'unlink':
        try:
            student_name = student.full_name
            student.managed_by.remove(request.user)
            
            teacher_classrooms = request.user.classrooms.all()
            for classroom in teacher_classrooms:
                classroom.students.remove(student)
                
            messages.success(request, f'{student_name}さんを担当から外しました。')
            return redirect('school_management:student_list')
        except Exception as e:
            messages.error(request, f'担当解除中にエラーが発生しました: {str(e)}')
            return redirect('school_management:student_delete_confirm', student_number=student_number)
            
    elif delete_type == 'hard_delete':
        try:
            student_name = student.full_name
            student.delete()
            messages.success(request, f'{student_name}さんをシステムから完全に削除しました。')
            return redirect('school_management:student_list')
        except Exception as e:
            messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
            return redirect('school_management:student_delete_confirm', student_number=student_number)
            
    else:
        messages.error(request, '無効な操作です。')
        return redirect('school_management:student_list')