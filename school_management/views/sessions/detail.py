from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import LessonSession, Quiz, StudentGoal, LessonReport

@login_required
def lesson_session_detail(request, session_id):
    """授業回詳細"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    quizzes = Quiz.objects.filter(lesson_session=session)

    classroom = session.classroom
    students = classroom.students.filter(role='student').order_by('student_number')

    if request.method == 'POST' and request.POST.get('action') == 'save_reports':
        saved_count = 0
        for student in students:
            field_name = f'report_{student.id}'
            report_text = request.POST.get(field_name, '').strip()
            if report_text:
                LessonReport.objects.update_or_create(
                    lesson_session=session,
                    student=student,
                    defaults={'report_text': report_text}
                )
                saved_count += 1
            else:
                LessonReport.objects.filter(lesson_session=session, student=student).delete()
        messages.success(request, f'日報を保存しました（{saved_count}件）。')
        return redirect('school_management:session_detail', session_id=session_id)

    # 各学生の現在の日報と目標を取得
    existing_reports = {
        r.student_id: r
        for r in LessonReport.objects.filter(lesson_session=session)
    }
    existing_goals = {
        g.student_id: g
        for g in StudentGoal.objects.filter(classroom=classroom, student__in=students)
    }
    student_report_data = []
    for student in students:
        student_report_data.append({
            'student': student,
            'report': existing_reports.get(student.id),
            'goal': existing_goals.get(student.id),
        })

    context = {
        'session': session,
        'quizzes': quizzes,
        'student_report_data': student_report_data,
    }
    return render(request, 'school_management/session_detail.html', context)
