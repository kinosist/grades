from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from ...models import LessonSession, Group, GroupMember

@login_required
def group_list_view(request, session_id):
    """グループ一覧表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student').order_by('group_number')
    
    # グループ統計情報を計算
    group_stats = []
    for group in groups:
        member_count = group.groupmember_set.count()
        group_stats.append({
            'group': group,
            'member_count': member_count,
            'members': group.groupmember_set.all()
        })
    
    # 実際にグループに所属しているユニークな学生数を計算
    assigned_student_ids = GroupMember.objects.filter(
        group__lesson_session=lesson_session
    ).values_list('student_id', flat=True).distinct()
    assigned_students_count = len(assigned_student_ids)
    
    # 総学生数と未配置学生数を計算
    total_students = lesson_session.classroom.students.count()
    unassigned_students = total_students - assigned_students_count
    
    context = {
        'lesson_session': lesson_session,
        'group_stats': group_stats,
        'total_students': total_students,
        'assigned_students': assigned_students_count,
        'unassigned_students': unassigned_students,
    }
    return render(request, 'school_management/group_list.html', context)

@login_required
def group_detail_view(request, session_id, group_id):
    """グループ詳細表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    members = group.groupmember_set.all().select_related('student')
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
        'members': members,
    }
    return render(request, 'school_management/group_detail.html', context)