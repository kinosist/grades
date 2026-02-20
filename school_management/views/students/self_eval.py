from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from ...models import (
    ClassRoom, LessonSession, CustomUser,
    StudentGoal, LessonReport, SelfEvaluation
)


@login_required
def student_goal_edit(request, class_id, student_number):
    """学生の目標を作成・編集（先生用）"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')

    if not classroom.students.filter(id=student.id).exists():
        messages.error(request, 'この学生は指定されたクラスに所属していません。')
        return redirect('school_management:class_detail', class_id=class_id)

    goal, _ = StudentGoal.objects.get_or_create(student=student, classroom=classroom)

    if request.method == 'POST':
        goal_text = request.POST.get('goal_text', '').strip()
        if goal_text:
            goal.goal_text = goal_text
            goal.save()
            messages.success(request, f'{student.full_name}さんの目標を保存しました。')
        else:
            messages.error(request, '目標を入力してください。')
        return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)

    # GET は class_student_detail へのリダイレクト（フォームはそっちに埋め込む）
    return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)


@login_required
def lesson_report_tab(request, session_id):
    """授業回の日報タブ: 全学生の日報一覧表示 & 一括保存"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    classroom = lesson_session.classroom
    students = classroom.students.filter(role='student').order_by('student_number')

    if request.method == 'POST':
        saved_count = 0
        for student in students:
            field_name = f'report_{student.id}'
            report_text = request.POST.get(field_name, '').strip()
            if report_text:
                LessonReport.objects.update_or_create(
                    lesson_session=lesson_session,
                    student=student,
                    defaults={'report_text': report_text}
                )
                saved_count += 1
            else:
                # テキストが空なら既存レコードを削除（クリア）
                LessonReport.objects.filter(
                    lesson_session=lesson_session,
                    student=student
                ).delete()
        messages.success(request, f'日報を保存しました（{saved_count}件）。')
        return redirect('school_management:lesson_session_detail', session_id=session_id)

    # 各学生の現在の日報と目標を取得
    existing_reports = {
        r.student_id: r
        for r in LessonReport.objects.filter(lesson_session=lesson_session)
    }
    existing_goals = {
        g.student_id: g
        for g in StudentGoal.objects.filter(classroom=classroom, student__in=students)
    }

    student_data = []
    for student in students:
        student_data.append({
            'student': student,
            'report': existing_reports.get(student.id),
            'goal': existing_goals.get(student.id),
        })

    context = {
        'lesson_session': lesson_session,
        'classroom': classroom,
        'student_data': student_data,
        'active_tab': 'reports',
    }
    return render(request, 'school_management/lesson_report_tab.html', context)


@login_required
def self_evaluation_edit(request, class_id, student_number):
    """学期末の自己評価・教師評価を入力（先生側）"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')

    if not classroom.students.filter(id=student.id).exists():
        messages.error(request, 'この学生は指定されたクラスに所属していません。')
        return redirect('school_management:class_detail', class_id=class_id)

    self_eval, _ = SelfEvaluation.objects.get_or_create(student=student, classroom=classroom)

    if request.method == 'POST':
        section = request.POST.get('section', 'teacher')  # 'teacher' or 'student'
        if section == 'teacher':
            teacher_comment = request.POST.get('teacher_comment', '').strip()
            teacher_score_raw = request.POST.get('teacher_score', '').strip()
            self_eval.teacher_comment = teacher_comment
            if teacher_score_raw:
                try:
                    score = int(teacher_score_raw)
                    if 0 <= score <= 100:
                        self_eval.teacher_score = score
                    else:
                        messages.error(request, '点数は0〜100で入力してください。')
                        return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)
                except ValueError:
                    messages.error(request, '点数は数値で入力してください。')
                    return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)
            else:
                self_eval.teacher_score = None
        elif section == 'student':
            student_comment = request.POST.get('student_comment', '').strip()
            student_score_raw = request.POST.get('student_score', '').strip()
            self_eval.student_comment = student_comment
            if student_score_raw:
                try:
                    score = int(student_score_raw)
                    if 0 <= score <= 100:
                        self_eval.student_score = score
                    else:
                        messages.error(request, '点数は0〜100で入力してください。')
                        return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)
                except ValueError:
                    messages.error(request, '点数は数値で入力してください。')
                    return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)
            else:
                self_eval.student_score = None

        self_eval.save()
        messages.success(request, '評価を保存しました。')
        return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)

    return redirect('school_management:class_student_detail', class_id=class_id, student_number=student_number)
