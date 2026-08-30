from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ...models import ClassRoomEnrollment, CustomUser, TeacherStudentAssignment


@login_required
def student_link_history_view(request):
    """担当から外した学生の履歴一覧（先生用）

    担当解除・除籍は物理削除ではなく is_active=False で記録されるため、
    過去に担当していた学生と、その学生が所属していたクラスを確認できる。
    """
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    inactive_assignments = TeacherStudentAssignment.objects.filter(
        teacher=request.user, is_active=False
    ).select_related('student').order_by('-unlinked_at')

    student_ids = [a.student_id for a in inactive_assignments]

    # N+1対策: 対象学生の在籍履歴（自分のクラスに限る）を一括取得
    enrollment_map = {}
    for enrollment in ClassRoomEnrollment.objects.filter(
        student_id__in=student_ids,
        classroom__teachers=request.user,
    ).select_related('classroom').order_by('-linked_at'):
        enrollment_map.setdefault(enrollment.student_id, []).append(enrollment)

    history_rows = []
    for assignment in inactive_assignments:
        history_rows.append({
            'student': assignment.student,
            'unlinked_at': assignment.unlinked_at,
            'linked_at': assignment.linked_at,
            'classroom_history': enrollment_map.get(assignment.student_id, []),
        })

    context = {
        'history_rows': history_rows,
    }
    return render(request, 'school_management/student_link_history.html', context)


@login_required
@require_POST
def student_relink_view(request, student_id):
    """履歴画面から、外した学生を再度自分の担当に戻す"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student = CustomUser.objects.filter(id=student_id, role='student').first()
    if not student:
        messages.error(request, '学生が見つかりません。')
        return redirect('school_management:student_link_history')

    # assign() が担当復元と同時に、以前在籍していたクラスへの在籍も自動的に復元する
    TeacherStudentAssignment.assign(request.user, student)

    messages.success(request, f'{student.full_name}さんを再度担当にし、以前所属していたクラスにも再度紐づけました。')
    return redirect('school_management:student_link_history')
