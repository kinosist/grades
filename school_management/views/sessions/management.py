from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import ClassRoom, LessonSession, Quiz, QuizScore
from django.db import IntegrityError

@login_required
def session_create_view(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic')
        has_quiz = request.POST.get('has_quiz') == 'on'
        has_peer_evaluation = request.POST.get('has_peer_evaluation') == 'on'
        if session_number and date:
            try:
                session = LessonSession.objects.create(
                    classroom=classroom,
                    session_number=int(session_number),
                    date=date,
                    topic=topic or "",
                    has_quiz=has_quiz,
                    has_peer_evaluation=has_peer_evaluation
                )
                messages.success(request, f'第{session_number}回授業を作成しました。')
                return redirect('school_management:session_detail', session_id=session.id)
            except IntegrityError:
                messages.warning(request, f'第{session_number}回は既に作成されています。別の回番号を指定してください。')
            except (ValueError, Exception) as e:
                messages.error(request, f'作成に失敗しました: {str(e)}')
        else:
            messages.error(request, '授業回と日付は必須です。')
    
    # 次の授業回番号を提案
    last_session = LessonSession.objects.filter(classroom=classroom).order_by('-session_number').first()
    next_session_number = (last_session.session_number + 1) if last_session else 1
    
    context = {
        'classroom': classroom,
        'next_session_number': next_session_number,
    }
    return render(request, 'school_management/session_create.html', context)

@login_required
def session_initialize_qr(request, session_id):
    """授業回にQRアクション点枠を作成（旧データ互換用）"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if not session.quiz_set.filter(is_qr_linked=True).exists():
        # 既存の小テストがあるか確認
        existing_quiz = Quiz.objects.filter(lesson_session=session).first()
        
        if existing_quiz:
            existing_quiz.is_qr_linked = True
            existing_quiz.save()
            messages.success(request, f'既存の小テスト「{existing_quiz.quiz_name}」をQRアクション点枠として設定しました。')
        else:
            Quiz.objects.create(
                lesson_session=session,
                quiz_name="QRアクション点",
                max_score=100,
                grading_method='qr_mobile',
                is_qr_linked=True
            )
            messages.success(request, 'QRアクション点枠を作成しました。')
    else:
        messages.info(request, '既にQRアクション点枠が存在します。')
        
    return redirect('school_management:session_detail', session_id=session.id)

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