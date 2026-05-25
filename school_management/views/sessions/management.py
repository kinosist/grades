from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import ClassRoom, LessonSession, Quiz, QuizScore, QRCodeScan, PeerEvaluation, Group, Attendance, StudentLessonPoints, LessonReport
from django.db import IntegrityError, transaction
from datetime import datetime

@login_required
def session_create_view(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        # Single session creation
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic')
        if session_number and date:
            try:
                session = LessonSession.objects.create(
                    classroom=classroom,
                    session_number=int(session_number),
                    date=date,
                    topic=topic or "",
                    has_peer_evaluation=True
                )
                messages.success(request, f'第{session_number}回授業を作成しました。')
                return redirect('school_management:session_detail', session_id=session.id)
            except IntegrityError:
                messages.warning(request, f'第{session_number}回は既に作成されています。別の回番号を指定してください。')
            except (ValueError, Exception) as e:
                messages.error(request, f'作成に失敗しました: {str(e)}')
        else:
            messages.error(request, '授業回と日付は必須です。')
    
    # 利用可能な授業回番号を計算
    existing_session_numbers = set(
        LessonSession.objects.filter(classroom=classroom).values_list('session_number', flat=True)
    )
    # 15回までを標準とする
    available_numbers = [num for num in range(1, 16) if num not in existing_session_numbers]
    
    context = {
        'classroom': classroom,
        'available_numbers': available_numbers,
    }
    return render(request, 'school_management/session_create.html', context)

@login_required
def merge_duplicate_quizzes(request, session_id):
    """重複した小テストを統合する"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        quizzes = Quiz.objects.filter(lesson_session=session).order_by('created_at')
        
        if quizzes.count() > 1:
            primary_quiz = quizzes.first()
            duplicate_quizzes = quizzes[1:]
            
            merged_scores_count = 0
            deleted_quizzes_count = 0

            for dup_quiz in duplicate_quizzes:
                for score_to_move in dup_quiz.quizscore_set.all():
                    primary_score, created = QuizScore.objects.get_or_create(
                        quiz=primary_quiz,
                        student=score_to_move.student,
                        defaults={'score': 0, 'graded_by': score_to_move.graded_by}
                    )
                    primary_score.score += score_to_move.score
                    primary_score.save()
                    merged_scores_count += 1
                
                dup_quiz.delete()
                deleted_quizzes_count += 1
            
            messages.success(request, f"{deleted_quizzes_count}件の重複した小テストを統合し、{merged_scores_count}件のスコアを移動しました。")
        else:
            messages.info(request, "重複した小テストはありません。")
            
    return redirect('school_management:session_detail', session_id=session.id)

@login_required
def session_reset_qr(request, session_id):
    """授業回の小テスト・QRデータをリセット（全削除して再作成）"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        # 関連するQRコードスキャン履歴も削除（整合性を保つため）
        scan_count = QRCodeScan.objects.filter(lesson_session=session).count()
        QRCodeScan.objects.filter(lesson_session=session).delete()

        # 既存の小テストを全て削除
        # これにより紐づくQuizScoreもCASCADEで削除されます
        count = session.quiz_set.count()
        session.quiz_set.all().delete()
        
        # 新しいQR用小テストを作成
        Quiz.objects.create(
            lesson_session=session,
            quiz_name="QRアクション点",
            max_score=100,
            grading_method='qr_mobile',
            is_qr_linked=True
        )
        
        messages.success(request, f'データをリセットしました。旧データ{count}件とスキャン履歴{scan_count}件を削除し、新しいQRアクション点枠を作成しました。')
        
    return redirect('school_management:session_detail', session_id=session.id)

@login_required
def lesson_session_delete(request, session_id):
    """授業回削除"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        classroom_id = session.classroom.id
        
        # 外部キー制約エラーを回避するため、関連データを明示的に全削除
        # 削除順序が重要（依存される側を後に消すのが基本）
        
        # 1. ピア評価関連 (Groupに依存しているため先に削除)
        PeerEvaluation.objects.filter(lesson_session=session).delete()
        
        # 2. グループ関連 (Sessionに依存)
        Group.objects.filter(lesson_session=session).delete()
        
        # 3. 小テスト・QR関連
        # Quizを消すとQuizScoreも消える
        Quiz.objects.filter(lesson_session=session).delete()
        # QRCodeScanを消す (QuizScore再計算シグナルが走るがQuizがないので安全にスキップされる)
        QRCodeScan.objects.filter(lesson_session=session).delete()
        
        # 4. その他 (Attendance, StudentLessonPoints, LessonReport)
        Attendance.objects.filter(lesson_session=session).delete()
        StudentLessonPoints.objects.filter(lesson_session=session).delete()
        LessonReport.objects.filter(lesson_session=session).delete()
        
        # 5. 本体削除
        session.delete()
        messages.success(request, '授業回を削除しました。')
        return redirect('school_management:class_detail', class_id=classroom_id)
    
    return redirect('school_management:session_detail', session_id=session.id)

@login_required
def session_bulk_edit_view(request, class_id):
    """授業回の一括作成・編集"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    # 既存の授業回を辞書に格納して高速アクセスできるようにする
    existing_sessions_map = {
        s.session_number: s 
        for s in LessonSession.objects.filter(classroom=classroom)
    }

    # ユーザーの意図（作成か編集か）をクエリパラメータから判断する
    mode = request.GET.get('mode', 'edit') # デフォルトは編集モード

    if request.method == 'POST':
        sessions_to_update = []
        sessions_to_create_data = [] # 新規作成するセッションのデータを格納

        # フォームから送信された授業回番号のみを処理対象とする
        submitted_numbers = set()
        for key in request.POST:
            if key.startswith('date-') or key.startswith('topic-'):
                try:
                    num = int(key.split('-')[1])
                    # 1~15 の範囲チェック
                    if 1 <= num <= 15:
                        submitted_numbers.add(num)
                except (ValueError, IndexError):
                    continue

        for num in sorted(list(submitted_numbers)):
            date_str = request.POST.get(f'date-{num}')
            topic_str = request.POST.get(f'topic-{num}', '').strip()

            new_date = None
            if date_str:
                try:
                    new_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    # 不正な日付フォーマット: エラーメッセージを出力して続ける
                    messages.error(request, f'第{num}回の日付 [{date_str}] は正しい形式ではありません。YYYY-MM-DD 形式でご入力ください。')
                    continue
            
            if num in existing_sessions_map:
                # 既存の授業回を更新
                session_obj = existing_sessions_map[num]
                if session_obj.date != new_date or session_obj.topic != topic_str:
                    session_obj.date = new_date
                    session_obj.topic = topic_str
                    sessions_to_update.append(session_obj)
            else:
                # 新しい授業回を作成
                # 「一括作成」モードからのPOSTでは、入力がなくても授業回の枠を作成する
                sessions_to_create_data.append({
                    'session_number': num,
                    'date': new_date,
                    'topic': topic_str,
                    'has_peer_evaluation': True
                })

        if sessions_to_create_data or sessions_to_update:
            actual_created_count = 0
            actual_skipped_count = 0 # 競合によりスキップされた数
            try:
                with transaction.atomic(): # トランザクションで一括処理
                    for session_data in sessions_to_create_data:
                        session_obj, created = LessonSession.objects.update_or_create(
                            classroom=classroom,
                            session_number=session_data['session_number'],
                            defaults={
                                'date': session_data['date'],
                                'topic': session_data['topic'],
                                'has_peer_evaluation': session_data['has_peer_evaluation']
                            }
                        )
                        if created:
                            actual_created_count += 1
                        else:
                            actual_skipped_count += 1

                    if sessions_to_update:
                        # bulk_updateは更新するフィールドを指定する必要がある
                        # ここではdateとtopicのみを更新対象とする
                        LessonSession.objects.bulk_update(sessions_to_update, ['date', 'topic'])
            except IntegrityError as e:
                messages.error(request, f'データベースの整合性エラーが発生しました。入力内容を確認してください: {e}')
                return redirect('school_management:class_detail', class_id=classroom.id)
            except Exception as e:
                messages.error(request, f'授業回の一括処理中に予期せぬエラーが発生しました: {e}')
                return redirect('school_management:class_detail', class_id=classroom.id)

            message_parts = []
            if actual_created_count > 0:
                message_parts.append(f'{actual_created_count}件の授業回を新規作成')
            if len(sessions_to_update) > 0:
                message_parts.append(f'{len(sessions_to_update)}件の授業回を更新')
            if actual_skipped_count > 0:
                message_parts.append(f'{actual_skipped_count}件の授業回は既に存在していたためスキップ')

            if message_parts:
                messages.success(request, '、'.join(message_parts) + 'しました。')
            else:
                messages.info(request, '変更された項目はありませんでした。')
        else:
            messages.info(request, '変更された項目はありませんでした。')
        
        return redirect('school_management:class_detail', class_id=classroom.id)

    # GETリクエストの処理
    sessions_to_display = []
    is_creation_mode = False # デフォルトは編集モード

    if mode == 'create':
        # 「一括作成」モード: 未作成の授業回のみをリストアップ
        for num in range(1, 16):
            if num not in existing_sessions_map:
                sessions_to_display.append(
                    LessonSession(classroom=classroom, session_number=num, date=None, topic="")
                )
        
        if sessions_to_display:
            is_creation_mode = True
        else:
            # 作成対象がない場合、編集モードとして既存の全件を表示する
            messages.info(request, 'すべての授業回（1～15回）が作成済みのため、編集モードで表示します。')
            sessions_to_display = sorted(list(existing_sessions_map.values()), key=lambda s: s.session_number)
            is_creation_mode = False
    else:
        # 「一括編集」モード: 作成済みの授業回のみを表示
        sessions_to_display = sorted(list(existing_sessions_map.values()), key=lambda s: s.session_number)
        if not sessions_to_display:
            messages.info(request, '編集可能な授業回がありません。まず授業回を作成してください。')
            return redirect('school_management:session_create', class_id=classroom.id)
        is_creation_mode = False
    
    context = {
        'classroom': classroom,
        'sessions': sessions_to_display,
        'is_creation_mode': is_creation_mode,
    }
    return render(request, 'school_management/session_bulk_edit.html', context)

@login_required
def session_edit_view(request, session_id):
    """授業回編集"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        date_str = request.POST.get('date')
        topic = request.POST.get('topic', '').strip()
        
        try:
            parsed_date = None
            if date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            session.date = parsed_date
            session.topic = topic
            session.save(update_fields=['date', 'topic'])
            messages.success(request, f'第{session.session_number}回の情報を更新しました。')
            return redirect('school_management:session_detail', session_id=session.id)
        except ValueError:
            messages.error(request, '日付は YYYY-MM-DD 形式でご入力ください。')
        except Exception as e:
            messages.error(request, f'更新中にエラーが発生しました: {e}')
    
    context = {
        'session': session,
    }
    return render(request, 'school_management/session_edit.html', context)