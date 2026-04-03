from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Sum, Q

from ...models import ClassRoom, CustomUser, StudentClassPoints, StudentLessonPoints, SelfEvaluation, QuizScore, \
    ContributionEvaluation, GroupMember, PeerEvaluation, LessonSession, Group


@login_required
@require_POST
def update_attendance_rate(request, class_id):
    """
    出席率を非同期で更新するAPI
    """
    import json

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
        # save()メソッド内でcalculate_points_internalが呼ばれ、points(合計点)も再計算されるため
        # update_fieldsを指定せずに保存して、pointsの変更もDBに反映させる
        student_class_points.save()
    else:
        student_class_points.save()

    return JsonResponse({'success': True, 'message': '出席率を保存しました'})


@login_required
@require_POST
def update_goal_score(request, class_id):
    """
    目標管理モード時の講師評価点を非同期で更新するAPI
    """
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
    """
    クラスごとのポイント一覧を表示するビュー
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    grading_system = classroom.grading_system
    students = classroom.students.all().order_by('student_number')

    # ===== N+1問題対策: クラス全体の投票データを一度に取得して事前集計 =====
    from ...models import Group

    # このクラスの全セッションを取得
    all_sessions = classroom.lessonsession_set.all()
    session_ids = list(all_sessions.values_list('id', flat=True))

    # 全セッションのグループと投票データを一括取得
    all_groups = Group.objects.filter(lesson_session__in=session_ids).select_related('lesson_session')
    all_peer_evals = PeerEvaluation.objects.filter(lesson_session__in=session_ids)

    # セッションごとのランキング情報をキャッシュ
    session_rankings_cache = {}

    for sess in all_sessions:
        sess_id = sess.id
        # そのセッションのグループを抽出
        session_groups = [g for g in all_groups if g.lesson_session_id == sess_id]
        # そのセッションの投票を抽出
        session_peer_evals = [pe for pe in all_peer_evals if pe.lesson_session_id == sess_id]

        # グループごとの投票スコアを計算
        group_scores = {}
        for group_obj in session_groups:
            first_votes = sum(
                1 for pe in session_peer_evals
                if (pe.first_place_group_id == group_obj.id or
                    pe.first_place_group_number == group_obj.group_number)
            )
            second_votes = sum(
                1 for pe in session_peer_evals
                if (pe.second_place_group_id == group_obj.id or
                    pe.second_place_group_number == group_obj.group_number)
            )
            score = (first_votes * 2) + (second_votes * 1)
            group_scores[group_obj.id] = score

        # ユニークなスコアを取得し、上位2つを特定
        unique_scores = sorted(list(set(group_scores.values())), reverse=True)
        top_2_scores = set(unique_scores[:2]) if len(unique_scores) >= 2 else set(unique_scores)

        # キャッシュに保存
        session_rankings_cache[sess_id] = {
            'group_scores': group_scores,
            'top_2_scores': top_2_scores
        }

    # ===== 各学生のクラス内成績を取得 =====
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

        # 投票ポイント: 事前計算されたキャッシュを利用してN+1問題を解決
        student_groups = GroupMember.objects.filter(
            student=student,
            group__lesson_session__classroom=classroom
        ).select_related('group', 'group__lesson_session')

        for membership in student_groups:
            group = membership.group
            sess = group.lesson_session
            sess_id = sess.id

            # キャッシュからランキング情報を取得
            if sess_id in session_rankings_cache:
                ranking_info = session_rankings_cache[sess_id]
                my_score = ranking_info['group_scores'].get(group.id, 0)
                top_2_scores = ranking_info['top_2_scores']

                # 上位2位のみポイント付付与
                vote_points = my_score if (my_score > 0 and my_score in top_2_scores) else 0

                # 表示用に記録
                if vote_points > 0 or my_score > 0:
                    if sess_id not in session_peer_map:
                        session_peer_map[sess_id] = {
                            'session': sess,
                            'contrib': 0, 'vote': 0
                        }
                    session_peer_map[sess_id]['vote'] += vote_points

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

        # ポイント一覧では、モードに関わらず純粋な獲得ポイント（積み上げ）を表示する
        # これにより、目標管理モードでも日々の活動量（QRやピア評価）を確認できる
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
def update_class_settings(request, class_id):
    """
    クラス設定（評価システム、QRポイント、出席点など）を更新するビュー
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    # 1. 評価システムの更新
    grading_system = request.POST.get('grading_system')
    recalculate_points = False
    
    # ✨ 修正ポイント：models.py の GRADING_SYSTEM_CHOICES に合わせて許可リストを更新
    if grading_system in ['default', 'original', 'goal']:
        if classroom.grading_system != grading_system:
            classroom.grading_system = grading_system
            recalculate_points = True
            messages.success(request, '評価システムを更新しました。')
        else:
            messages.info(request, '評価システムは変更されていません。')

    # 2. QRポイントの更新
    qr_point_value = request.POST.get('qr_point_value')
    if qr_point_value:
        try:
            val = int(qr_point_value)
            if 0 < val <= 100:
                if classroom.qr_point_value != val:
                    classroom.qr_point_value = val
                    messages.success(request, 'QRアクションポイントを更新しました。')
                else:
                    messages.info(request, 'QRアクションポイントは変更されていません。')
            else:
                messages.error(request, 'QRアクションポイントは1〜100の間で設定してください。')
        except ValueError:
            pass

    # 3. 出席点満点の更新
    attendance_max_points = request.POST.get('attendance_max_points')
    recalculate_attendance = False
    if attendance_max_points:
        try:
            val = int(attendance_max_points)
            if 0 <= val <= 1000:
                if classroom.attendance_max_points != val:
                    classroom.attendance_max_points = val
                    recalculate_attendance = True
                    messages.success(request, '出席点満点を更新しました。')
                else:
                    messages.info(request, '出席点満点は変更されていません。')
            else:
                messages.error(request, '出席点満点は0〜1000の間で設定してください。')
        except ValueError:
            pass

    classroom.save()

    # 評価システムが変更された場合、全学生のポイントを再計算（モード切替）
    if recalculate_points:
        scps = StudentClassPoints.objects.filter(classroom=classroom)
        for scp in scps:
            scp.save()  # save()時に calculate_points_internal が走り、モードに応じた計算が行われる

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