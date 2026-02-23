import json
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Sum, Q, Count
from ...models import ClassRoom, CustomUser, StudentClassPoints, StudentLessonPoints, SelfEvaluation, QuizScore, ContributionEvaluation, GroupMember, PeerEvaluation

@login_required
@require_POST
def update_attendance_rate(request, class_id):
    """出席率を更新するAPI"""
    import json
    from django.views.decorators.csrf import csrf_exempt
    
    # JSONリクエストを受け取る
    data = json.loads(request.body)
    student_id = data.get('student_id')
    attendance_rate = data.get('attendance_rate')
    attendance_points = data.get('attendance_points', 0)
    
    # バリデーション
    if not student_id or attendance_rate is None:
        return JsonResponse({'success': False, 'error': 'パラメータが不足しています'})
    
    if not (0 <= attendance_rate <= 100):
        return JsonResponse({'success': False, 'error': '出席率は0〜100の範囲で入力してください'})
    
    # クラスと学生を取得
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, id=student_id)
    
    # 学生がクラスに所属しているか確認
    if not classroom.students.filter(id=student_id).exists():
        return JsonResponse({'success': False, 'error': 'この学生はクラスに所属していません'})
    
    # 出席率、出席点、合計点をデータベースに保存
    student_class_points, created = StudentClassPoints.objects.get_or_create(
        student=student,
        classroom=classroom,
        defaults={'points': 0, 'attendance_rate': attendance_rate, 'attendance_points': attendance_points}
    )
    
    if not created:
        # 既存のレコードの出席率、出席点を更新（ポイントは更新しない）
        student_class_points.attendance_rate = attendance_rate
        student_class_points.attendance_points = attendance_points
        student_class_points.save(update_fields=['attendance_rate', 'attendance_points'])
    else:
        student_class_points.save(update_fields=['attendance_rate', 'attendance_points'])
    
    return JsonResponse({'success': True, 'message': '出席率を保存しました'})

@login_required
@require_POST
def update_goal_score(request, class_id):
    """目標管理モード時の講師評価点を更新するAPI"""
    import json
    
    # JSONリクエストを受け取る
    data = json.loads(request.body)
    student_id = data.get('student_id')
    score = data.get('score')
    
    if not student_id or score is None:
        return JsonResponse({'success': False, 'error': 'パラメータが不足しています'})
        
    try:
        score = int(score)
    except ValueError:
        return JsonResponse({'success': False, 'error': '点数は数値で入力してください'})

    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, id=student_id)

    # 1. SelfEvaluation（自己評価・講師評価）を更新
    self_eval, _ = SelfEvaluation.objects.get_or_create(
        student=student,
        classroom=classroom
    )
    self_eval.teacher_score = score
    self_eval.save()

    # 2. StudentClassPointsを更新（再計算トリガー）
    # models.pyのロジックにより、grading_system='goal'ならteacher_scoreがpointsに反映される
    scp, _ = StudentClassPoints.objects.get_or_create(student=student, classroom=classroom)
    scp.save()

    return JsonResponse({'success': True, 'message': '評価点を保存しました'})

@login_required
def class_points_view(request, class_id):
    """クラスごとのポイント一覧"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    grading_system = classroom.grading_system
    students = classroom.students.all().order_by('student_number')
    
    # 各学生のクラス内成績を取得
    student_grades = []
    
    for student in students:
        # 1. 授業内手動ポイント (StudentLessonPoints)
        lesson_points_qs = StudentLessonPoints.objects.filter(
            student=student,
            lesson_session__classroom=classroom
        ).select_related('lesson_session').order_by('lesson_session__session_number')
        lesson_total = sum(p.points for p in lesson_points_qs)
        
        # 2. 小テスト/QRポイント (QuizScore)
        all_quiz_scores = QuizScore.objects.filter(
            student=student,
            quiz__lesson_session__classroom=classroom,
            is_cancelled=False
        ).select_related('quiz', 'quiz__lesson_session').order_by('quiz__lesson_session__session_number')
        
        # 重複対策: 同一クイズは最新のみ
        quiz_score_dict = {}
        for qs in all_quiz_scores:
            quiz_score_dict[qs.quiz.id] = qs
        unique_quiz_scores = list(quiz_score_dict.values())
        unique_quiz_scores.sort(key=lambda x: x.quiz.lesson_session.session_number)
        
        quiz_total = sum(qs.score for qs in unique_quiz_scores)
        
        # 3. ピア評価ポイント
        peer_total = 0
        peer_details = []
        
        # 貢献度
        contrib_evals = ContributionEvaluation.objects.filter(
            evaluatee=student,
            peer_evaluation__lesson_session__classroom=classroom
        ).select_related('peer_evaluation__lesson_session')
        
        session_peer_map = {}
        for ce in contrib_evals:
            sess_id = ce.peer_evaluation.lesson_session.id
            if sess_id not in session_peer_map:
                session_peer_map[sess_id] = {
                    'session': ce.peer_evaluation.lesson_session,
                    'contrib': 0, 'vote': 0
                }
            session_peer_map[sess_id]['contrib'] += ce.contribution_score
            
        # 投票
        student_groups = GroupMember.objects.filter(
            student=student, 
            group__lesson_session__classroom=classroom
        ).select_related('group', 'group__lesson_session')
        
        for membership in student_groups:
            group = membership.group
            sess = group.lesson_session
            
            # ランキング判定
            # セッション内の全グループのスコアを計算
            # 注意: ループ内でクエリを発行するため学生数が多いと重くなる可能性がありますが、正確性を優先します
            from ...models import Group
            session_groups = Group.objects.filter(lesson_session=sess)
            group_scores = []
            for g in session_groups:
                f = PeerEvaluation.objects.filter(Q(first_place_group=g) | Q(lesson_session=sess, first_place_group_number=g.group_number)).distinct().count()
                s = PeerEvaluation.objects.filter(Q(second_place_group=g) | Q(lesson_session=sess, second_place_group_number=g.group_number)).distinct().count()
                group_scores.append((f * 2) + (s * 1))
            
            unique_scores = sorted(list(set(group_scores)), reverse=True)
            top_2_scores = unique_scores[:2]
            
            # 自分のスコア
            first_votes = PeerEvaluation.objects.filter(Q(first_place_group=group) | Q(lesson_session=sess, first_place_group_number=group.group_number)).distinct().count()
            second_votes = PeerEvaluation.objects.filter(Q(second_place_group=group) | Q(lesson_session=sess, second_place_group_number=group.group_number)).distinct().count()
            my_score = (first_votes * 2) + (second_votes * 1)
            
            # 上位2位のみポイント付与
            vote_points = my_score if (my_score > 0 and my_score in top_2_scores) else 0
            
            # 表示用に記録（0点でも履歴には残す場合は条件を調整、ここではポイントがある場合のみマップに追加）
            if vote_points > 0 or my_score > 0: # 順位外でもスコアがあれば履歴には表示したい場合
                if sess.id not in session_peer_map:
                    session_peer_map[sess.id] = {
                        'session': sess,
                        'contrib': 0, 'vote': 0
                    }
                session_peer_map[sess.id]['vote'] += vote_points
        
        for data in session_peer_map.values():
            p_sum = data['contrib'] + data['vote']
            peer_total += p_sum
            peer_details.append({
                'session': data['session'],
                'contrib': data['contrib'],
                'vote': data['vote'],
                'total': p_sum
            })
        peer_details.sort(key=lambda x: x['session'].session_number)

        # 純粋な合計ポイント (QR + ピア + その他)
        raw_total_points = lesson_total + quiz_total + peer_total

        # DB保存値（目標管理モード用）
        try:
            scp = StudentClassPoints.objects.get(student=student, classroom=classroom)
            db_points = scp.points
            attendance_points = scp.attendance_points
        except StudentClassPoints.DoesNotExist:
            db_points = 0
            attendance_points = 0

        # 表示用ポイント: 目標管理モードならDB値、通常なら計算式 (QR+ピア+その他+出席)*2
        if grading_system == 'goal':
            display_points = db_points
        else:
            # ポイント一覧では純粋な獲得ポイントのみを表示（出席点や倍率は含めない）
            display_points = raw_total_points

        # 評価レベル判定（仮: 授業回あたりの平均などで判定していたロジックを維持）
        session_count = lesson_points_qs.count()
        lesson_average = round(lesson_total / session_count, 1) if session_count > 0 else 0
        
        if lesson_average >= 5:
            grade_level = '優秀'
            grade_color = 'success'
        elif lesson_average >= 3:
            grade_level = '良好'
            grade_color = 'warning'
        elif lesson_average >= 1:
            grade_level = '普通'
            grade_color = 'info'
        else:
            grade_level = '要努力'
            grade_color = 'secondary'

        student_grades.append({
            'student': student,
            'total_points': display_points,  # 一覧の「総ポイント」列に使用
            'raw_total_points': raw_total_points,
            'quiz_total': quiz_total,
            'peer_total': peer_total,
            'lesson_total': lesson_total,
            'attendance_points': attendance_points,
            'average_points': lesson_average,
            'session_count': session_count,
            'lesson_points': lesson_points_qs,
            'quiz_scores': unique_quiz_scores,
            'peer_details': peer_details,
            'grade_level': grade_level,
            'grade_color': grade_color,
            'overall_points': student.points,  # 全体のポイント（参考用）
            'class_points': display_points,
        })
    
    # 合計ポイント順でソート
    student_grades.sort(key=lambda x: x['total_points'], reverse=True)
    
    # クラス全体の統計
    total_students = len(student_grades)
    if total_students > 0:
        class_average = round(sum(grade['total_points'] for grade in student_grades) / total_students, 1)
        max_average = max(grade['total_points'] for grade in student_grades)
        min_average = min(grade['total_points'] for grade in student_grades)
    else:
        class_average = 0
        max_average = 0
        min_average = 0
    
    context = {
        'classroom': classroom,
        'grading_system': grading_system,
        'student_grades': student_grades,
        'class_stats': {
            'total_students': total_students,
            'class_average': class_average,
            'max_average': max_average,
            'min_average': min_average,
        }
    }
    return render(request, 'school_management/class_points.html', context)

@login_required
@require_POST
def update_class_settings(request, class_id):
    """クラス設定（QRポイントなど）を更新"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    # 評価システムの更新
    grading_system = request.POST.get('grading_system')
    recalculate_points = False
    if grading_system in ['standard', 'goal']:
        if classroom.grading_system != grading_system:
            classroom.grading_system = grading_system
            recalculate_points = True

    # QRポイントの更新
    qr_point_value = request.POST.get('qr_point_value')
    if qr_point_value:
        try:
            val = int(qr_point_value)
            if val > 0:
                classroom.qr_point_value = val
        except ValueError:
            pass
            
    # 出席点満点の更新
    attendance_max_points = request.POST.get('attendance_max_points')
    recalculate_attendance = False
    if attendance_max_points:
        try:
            val = int(attendance_max_points)
            if val >= 0:
                if classroom.attendance_max_points != val:
                    classroom.attendance_max_points = val
                    recalculate_attendance = True
        except ValueError:
            pass
            
    classroom.save()
    
    # 評価システムが変更された場合、全学生のポイントを再計算（モード切替）
    if recalculate_points:
        scps = StudentClassPoints.objects.filter(classroom=classroom)
        for scp in scps:
            scp.save() # save()時に calculate_points_internal が走り、モードに応じた計算が行われる

    # 出席点満点が変更された場合、全学生の出席点を再計算
    if recalculate_attendance:
        scps = StudentClassPoints.objects.filter(classroom=classroom)
        for scp in scps:
            # 出席点 = 出席率 * 満点 / 100
            scp.attendance_points = (scp.attendance_rate * classroom.attendance_max_points) / 100
            scp.save()  # save()で合計点も再計算される

    # リファラ（元のページ）に応じてリダイレクト先を調整
    referer = request.META.get('HTTP_REFERER', '')
    if 'qr-codes' in referer:
        return redirect(referer)
    if 'evaluation' in referer:
        return redirect(referer)
    
    return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=settings")