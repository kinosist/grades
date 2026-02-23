from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Sum
from ...models import ClassRoom, LessonSession, StudentLessonPoints, Quiz, QuizScore, Group, GroupMember, StudentClassPoints, PeerEvaluation, ContributionEvaluation 

@login_required
def class_evaluation_view(request, class_id):
    """クラスごとの評価一覧（写真のような形式）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    # 評価システム（通常 or 目標管理）
    grading_system = classroom.grading_system

    # 各学生の評価データを取得
    student_evaluations = []
    
    for student in students:
        # 各授業回のデータ（ポイント + ピア評価スコア）
        session_data = {}
        session_count = 0
        total_qr_points = 0
        
        for session in sessions:
            session_key = f"第{session.session_number}回"
            
            # QRコードポイントを取得
            qr_points = 0
            lesson_point = StudentLessonPoints.objects.filter(
                lesson_session=session,
                student=student
            ).first()
            if lesson_point:
                qr_points = lesson_point.points
                session_count += 1
                total_qr_points += qr_points
            
            # 小テストスコアを取得
            quiz_score = 0
            has_quiz = False
            try:
                quiz = Quiz.objects.filter(lesson_session=session).first()
                if quiz:
                    has_quiz = True
                    quiz_score_obj = QuizScore.objects.filter(
                        quiz=quiz,
                        student=student,
                        is_cancelled=False
                    ).first()
                    if quiz_score_obj:
                        # 小テストのスコア（0-100点）をそのまま使用
                        quiz_score = quiz_score_obj.score
            except Exception as e:
                print(f"小テストスコア取得エラー: {e}")
                pass
            
            # ピア評価スコアを取得（貢献度 + 投票ポイント）
            peer_evaluation_score = 0
            try:
                if session.has_peer_evaluation:
                    # 1. 貢献度評価 (5段階評価の合計)
                    contrib_score = ContributionEvaluation.objects.filter(
                        peer_evaluation__lesson_session=session,
                        evaluatee=student
                    ).aggregate(total=Sum('contribution_score'))['total'] or 0
                    
                    # 2. 投票ポイント (1位=2点, 2位=1点)
                    vote_score = 0
                    # この授業回での学生のグループを取得
                    membership = GroupMember.objects.filter(
                        student=student,
                        group__lesson_session=session
                    ).first()
                    
                    if membership:
                        group = membership.group
                        first_votes = PeerEvaluation.objects.filter(first_place_group=group).count()
                        second_votes = PeerEvaluation.objects.filter(second_place_group=group).count()
                        vote_score = (first_votes * 2) + (second_votes * 1)

                    peer_evaluation_score = contrib_score + vote_score
            except Exception as e:
                print(f"ピア評価スコア取得エラー: {e}")
                pass
            
            session_data[session_key] = {
                'qr_points': qr_points,
                'quiz_score': quiz_score,
                'peer_score': peer_evaluation_score,
                'total_score': qr_points + quiz_score + peer_evaluation_score,
                'date': session.date,
                'has_peer_evaluation': session.has_peer_evaluation,
                'has_quiz': has_quiz
            }
        
        # 出席率と平均ポイントを計算
        total_sessions = sessions.count()
        # データベースから保存された出席率、出席点、ポイントを取得
        attendance_rate = 0
        saved_attendance_points = 0
        saved_class_points = 0
        try:
            student_class_points = StudentClassPoints.objects.get(student=student, classroom=classroom)
            attendance_rate = student_class_points.attendance_rate
            saved_attendance_points = student_class_points.attendance_points
            saved_class_points = student_class_points.points
            # 旧データ互換: total値として保存されている場合は出席点を差し引く
            if saved_class_points and saved_attendance_points and saved_class_points >= saved_attendance_points:
                saved_class_points -= saved_attendance_points
        except StudentClassPoints.DoesNotExist:
            # 保存されていない場合は自動計算
            attendance_rate = (session_count / total_sessions * 100) if total_sessions > 0 else 0
        
        # 各種スコアの合計を計算
        total_peer_score = sum(data['peer_score'] for data in session_data.values())
        total_quiz_score = sum(data.get('quiz_score', 0) for data in session_data.values())
        total_combined_score = sum(data['total_score'] for data in session_data.values())
        
        # 出席点を使用（保存されたものがあればそれを使う）
        attendance_points_value = saved_attendance_points if saved_attendance_points > 0 else 0

        # 合計計算ロジックの変更
        # 授業点 = (小テスト(QR含む) + ピア評価 + 出席点 + 授業内ポイント) * 倍率
        multiplier_value = 2
        
        # total_combined_score には (QR + Quiz + Peer) が含まれている
        # ここに Attendance を足して倍率を掛ける
        base_points = total_combined_score + attendance_points_value
        
        # 目標管理モードの場合は、DBに保存されているポイント（講師評価点）を優先
        if grading_system == 'goal':
            total_points_calculated = saved_class_points
        else:
            total_points_calculated = int(base_points * multiplier_value)
        
        average_points = round(total_qr_points / session_count, 1) if session_count > 0 else 0
        
        student_evaluations.append({
            'student': student,
            'total_points': total_points_calculated,  # 合計点は出席点 + 点数
            'total_peer_score': total_peer_score,
            'total_quiz_score': total_quiz_score,  # 小テストスコアの合計
            'total_combined_score': total_combined_score,
            'attendance_points': attendance_points_value,  # 出席点（保存された値または0）
            'attendance_rate': attendance_rate,
            'multiplied_points': total_points_calculated,  # 倍率適用済みの点数
            'multiplier': multiplier_value,
            'session_data': session_data,
            'session_count': session_count,
            'average_points': average_points,
            'class_points': total_points_calculated,  # クラスのポイント
            'student_points': student.points,  # 学生の全体ポイント
            'qr_points': total_qr_points,  # クラスのQRコードポイントの合計
        })
    
    session_list = [f"第{session.session_number}回" for session in sessions]
    
    # 各授業回のピア評価平均値を計算
    session_peer_averages = {}
    for session in sessions:
        if session.has_peer_evaluation:
            peer_scores = ContributionEvaluation.objects.filter(
                peer_evaluation__lesson_session=session
            ).aggregate(avg_score=models.Avg('contribution_score'))
            
            avg_score = round(peer_scores['avg_score'] or 0, 1)
            session_peer_averages[session.id] = avg_score
            print(f"Session {session.session_number}: PE average = {avg_score}")
        else:
            session_peer_averages[session.id] = None
            print(f"Session {session.session_number}: No peer evaluation")
    
    print(f"Session peer averages: {session_peer_averages}")
    
    context = {
        'classroom': classroom,
        'student_evaluations': student_evaluations,
        'session_list': session_list,
        'sessions': sessions,  # 日付情報も渡す
        'session_peer_averages': session_peer_averages,  # ピア評価平均値
        'total_sessions': len(session_list),
        'grading_system': grading_system, # テンプレート側で表示切り替えに使用
    }
    return render(request, 'school_management/class_evaluation.html', context)
